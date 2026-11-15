"""Pontos de implementação da geração de comandos e expressões."""

import load_previous
from ir import Context, ProgramIR, FunctionIR
from selector import Selector
from catalogue import catalogue
from ast_nodes import (
    TypeName,
    Block,
    VarDecl,
    Assignment,
    CallStmt,
    IfStmt,
    WhileStmt,
    ReturnStmt,
    PrintStmt,
    StringLiteral,
)
from patterns import (
    REG,
    COND,
    IMM12,
    POW2,
    EFFECT,
    signed_literal,
)

import ir as I


class CodeGenerator:
    """Coordene comandos ad hoc e seleção de expressões com DP."""

    def __init__(self):
        self.selector = None
        self.ctx = None

    def generate(self, program):
        """Traduza funções e comandos. Selecione expressões com DP."""
        program_ir = ProgramIR()
        self.selector = Selector(catalogue())

        for func_declaration in program.functions:
            func_symbol = func_declaration.metadata["symbol"]
            func_ir = FunctionIR(func_symbol)
            program_ir.functions.append(func_ir)

            self.ctx = Context(func_ir, program_ir)

            # Aloca um registrador local para cada parâmetro e emite a instrução Param correspondente
            for index, param in enumerate(func_declaration.parameters):
                param_symbol = param.metadata["symbol"]
                dst_reg = self.ctx.variable(param_symbol)
                self.ctx.emit(I.Param(dst_reg, index, origin=param.span))

            self.statement(func_declaration.body)

            # Avalia se a função tem retorno void
            if func_symbol.type == TypeName.VOID or getattr(func_declaration, "return_type", None) == TypeName.VOID:
                # Avalia se o corpo da função ainda não termina com uma instrução de retorno
                if not func_ir.instructions or not isinstance(func_ir.instructions[-1], I.Return):
                    self.ctx.emit(I.Return(None, origin=func_declaration.span))

        return program_ir

    def statement(self, node):
        """Traduza um comando ad hoc."""
        # Avalia se o nó é um bloco de comandos agrupados
        if isinstance(node, Block):
            for stmt in node.statements:
                self.statement(stmt)

        # Avalia se o nó é uma declaração de variável
        elif isinstance(node, VarDecl):
            # Avalia se a variável possui expressão de inicialização
            if node.initializer is not None:
                val_reg = self.expression(node.initializer, REG)
                var_reg = self.ctx.variable(node.metadata["symbol"])
                self.ctx.emit(I.Move(var_reg, val_reg, origin=node.span))
            else:
                self.ctx.variable(node.metadata["symbol"])

        # Avalia se o nó é uma atribuição a uma variável existente
        elif isinstance(node, Assignment):
            val_reg = self.expression(node.value, REG)
            symbol = node.target.metadata.get("symbol") or node.metadata.get("symbol")
            var_reg = self.ctx.variable(symbol)
            self.ctx.emit(I.Move(var_reg, val_reg, origin=node.span))

        # Avalia se o nó é uma chamada de função isolada (sem uso do retorno)
        elif isinstance(node, CallStmt):
            self.expression(node.call, EFFECT)

        # Avalia se o nó é um comando de retorno
        elif isinstance(node, ReturnStmt):
            # Avalia se o retorno é vazio (sem valor associado)
            if node.value is None:
                self.ctx.emit(I.Return(None, origin=node.span))
            else:
                val_reg = self.expression(node.value, REG)
                self.ctx.emit(I.Return(val_reg, origin=node.span))

        # Avalia se o nó é uma estrutura condicional (if / if-else)
        elif isinstance(node, IfStmt):
            # Avalia se o condicional possui apenas o ramo verdadeiro (sem else)
            if node.else_block is None:
                then_label = self.ctx.label()
                end_label = self.ctx.label()

                # Avalia a condição desviando para then_label se verdadeira ou pulando para end_label se falsa;
                # em seguida marca then_label, gera o corpo do if e posiciona o rótulo de saída end_label.
                self.expression(node.condition, COND, true_label=then_label, false_label=end_label)
                self.ctx.emit(I.LabelInstr(then_label, origin=node.then_block.span))
                self.statement(node.then_block)
                self.ctx.emit(I.LabelInstr(end_label, origin=node.span))
            else:
                then_label = self.ctx.label()
                else_label = self.ctx.label()
                end_label = self.ctx.label()

                # Avalia a condição desviando para then_label ou else_label; executa o bloco then e emite um
                # salto incondicional (Jump) para end_label para não invadir o else; por fim, define o bloco else e o fim.
                self.expression(node.condition, COND, true_label=then_label, false_label=else_label)
                self.ctx.emit(I.LabelInstr(then_label, origin=node.then_block.span))
                self.statement(node.then_block)
                self.ctx.emit(I.Jump(end_label, origin=node.span))
                self.ctx.emit(I.LabelInstr(else_label, origin=node.else_block.span))
                self.statement(node.else_block)
                self.ctx.emit(I.LabelInstr(end_label, origin=node.span))

        # Avalia se o nó é um laço de repetição (while)
        elif isinstance(node, WhileStmt):
            start_label = self.ctx.label()
            body_label = self.ctx.label()
            end_label = self.ctx.label()

            # Marca o início do laço (start_label) e avalia a condição: se verdadeira, entra em body_label;
            # se falsa, sai para end_label. Após executar o corpo, salta de volta ao início para reavaliar.
            self.ctx.emit(I.LabelInstr(start_label, origin=node.span))
            self.expression(node.condition, COND, true_label=body_label, false_label=end_label)
            self.ctx.emit(I.LabelInstr(body_label, origin=node.body.span))
            self.statement(node.body)
            self.ctx.emit(I.Jump(start_label, origin=node.span))
            self.ctx.emit(I.LabelInstr(end_label, origin=node.span))

        # Avalia se o nó é um comando de impressão
        elif isinstance(node, PrintStmt):
            # Percorre cada item do print emitindo a instrução específica conforme o tipo e finaliza com '\n'
            for item in node.items:
                # Avalia se o item é uma string literal
                if isinstance(item, StringLiteral):
                    ref = self.ctx.string(item.value)
                    self.ctx.emit(I.PrintString(ref, origin=item.span))
                else:
                    val_reg = self.expression(item, REG)
                    # Avalia se o resultado da expressão é booleano ou inteiro
                    if item.metadata.get("type") == TypeName.BOOL:
                        self.ctx.emit(I.PrintBool(val_reg, origin=item.span))
                    else:
                        self.ctx.emit(I.PrintInt(val_reg, origin=item.span))
            newline_ref = self.ctx.string("\n")
            self.ctx.emit(I.PrintString(newline_ref, origin=node.span))

        else:
            raise ValueError(f"Comando não suportado: {type(node).__name__}")

    def expression(self, node, result_class, true_label=None, false_label=None):
        """Selecione e reconstrua uma expressão, preservando curto-circuito."""
        table = self.selector.analyze(node)
        choice = table.lookup(node, result_class)
        # Avalia se existe uma regra válida na tabela DP cobrindo este nó
        if choice is None:
            raise ValueError(f"Sem cobertura para {result_class} no nó em {node.span}")
        return self._emit_choice(node, result_class, table, true_label=true_label, false_label=false_label)

    def _emit_choice(self, node, result_class, table, true_label=None, false_label=None):
        choice = table.lookup(node, result_class)
        # Avalia se a subárvore possui cobertura para a classe de resultado esperada
        if choice is None:
            raise ValueError(f"Sem cobertura para {result_class} no nó em {node.span}")

        action = choice.rule.action

        # 4.1. Folhas e Literais
        # Avalia carregamento de constante inteira em registrador temporário
        if action == "li_int":
            dst = self.ctx.temp()
            self.ctx.emit(I.Li(dst, node.value, origin=node.span))
            return dst

        # Avalia carregamento de constante booleana (0 ou 1) em registrador
        if action == "li_bool":
            dst = self.ctx.temp()
            self.ctx.emit(I.Li(dst, int(node.value), origin=node.span))
            return dst

        # Avalia leitura de variável local ou parâmetro
        if action == "identifier":
            return self.ctx.variable(node.metadata["symbol"])

        # Avalia constante imediata de 12 bits com sinal
        if action == "imm12":
            return signed_literal(node)

        # Avalia literal potência de 2 extraindo seu expoente (log2)
        if action == "pow2":
            lit = signed_literal(node)
            return lit.bit_length() - 1

        # 4.2. Operações Aritméticas (REG)
        # Avalia negação aritmética unária (-x)
        if action == "neg":
            src = self._emit_choice(node.operand, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Neg(dst, src, origin=node.span))
            return dst

        # Avalia operações aritméticas binárias padrão entre dois registradores
        if action in ("add", "sub", "mul", "div", "rem"):
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            instr_map = {
                "add": I.Add,
                "sub": I.Sub,
                "mul": I.Mul,
                "div": I.Div,
                "rem": I.Rem,
            }
            self.ctx.emit(instr_map[action](dst, lhs, rhs, origin=node.span))
            return dst

        # Avalia adição com constante imediata à direita (reg + imm)
        if action == "addi_right":
            lhs = self._emit_choice(node.left, REG, table)
            imm = self._emit_choice(node.right, IMM12, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Addi(dst, lhs, imm, origin=node.span))
            return dst

        # Avalia adição com constante imediata à esquerda (imm + reg)
        if action == "addi_left":
            imm = self._emit_choice(node.left, IMM12, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Addi(dst, rhs, imm, origin=node.span))
            return dst

        # Avalia subtração por imediato à direita convertendo em soma com valor negado
        if action == "sub_imm_right":
            lhs = self._emit_choice(node.left, REG, table)
            imm = -signed_literal(node.right)
            dst = self.ctx.temp()
            self.ctx.emit(I.Addi(dst, lhs, imm, origin=node.span))
            return dst

        # Avalia multiplicação por potência de 2 à direita usando deslocamento lógico à esquerda
        if action == "slli_right":
            lhs = self._emit_choice(node.left, REG, table)
            shift = self._emit_choice(node.right, POW2, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slli(dst, lhs, shift, origin=node.span))
            return dst

        # Avalia multiplicação por potência de 2 à esquerda usando deslocamento lógico à esquerda
        if action == "slli_left":
            shift = self._emit_choice(node.left, POW2, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slli(dst, rhs, shift, origin=node.span))
            return dst

        # 4.3. Comparações para Valor Booleano (REG)
        # Avalia comparação "menor que" (<) salvando 0 ou 1 em registrador
        if action == "slt":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slt(dst, lhs, rhs, origin=node.span))
            return dst

        # Avalia comparação "maior que" (>) invertendo os operandos na instrução Slt
        if action == "sgt":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slt(dst, rhs, lhs, origin=node.span))
            return dst

        # Avalia comparação "menor ou igual" (<=) em registrador
        if action == "sle":
            # Calcula rhs < lhs via Slt e nega o resultado com Seqz (igual a zero) para obter lhs <= rhs
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slt(dst, rhs, lhs, origin=node.span))
            self.ctx.emit(I.Seqz(dst, dst, origin=node.span))
            return dst

        # Avalia comparação "maior ou igual" (>=) em registrador
        if action == "sge":
            # Calcula lhs < rhs via Slt e inverte o bit booleano com Seqz para obter lhs >= rhs
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slt(dst, lhs, rhs, origin=node.span))
            self.ctx.emit(I.Seqz(dst, dst, origin=node.span))
            return dst

        # Avalia comparação de igualdade (==) em registrador
        if action == "seq":
            # Aplica Xor entre os operandos (zera se forem iguais) e testa se o resultado é zero com Seqz
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Xor(dst, lhs, rhs, origin=node.span))
            self.ctx.emit(I.Seqz(dst, dst, origin=node.span))
            return dst

        # Avalia comparação de desigualdade (!=) em registrador
        if action == "sne":
            # Aplica Xor entre os operandos e verifica se há diferença (diferente de zero) via Snez
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Xor(dst, lhs, rhs, origin=node.span))
            self.ctx.emit(I.Snez(dst, dst, origin=node.span))
            return dst

        # 4.4. Comparações Diretas para Controle (COND)
        # Avalia desvio condicional para "menor que" (<)
        if action == "branch_lt":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Blt(lhs, rhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        # Avalia desvio condicional para "maior ou igual" (>=)
        if action == "branch_ge":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Bge(lhs, rhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        # Avalia desvio condicional para "maior que" (>) invertendo os operandos em Blt
        if action == "branch_gt":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Blt(rhs, lhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        # Avalia desvio condicional para "menor ou igual" (<=) invertendo os operandos em Bge
        if action == "branch_le":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Bge(rhs, lhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        # Avalia desvio condicional para igualdade (==)
        if action == "branch_eq":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Beq(lhs, rhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        # Avalia desvio condicional para desigualdade (!=)
        if action == "branch_ne":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Bne(lhs, rhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        # 4.5. Operadores Lógicos, Curto-Circuito e Folhas Booleanas
        # Avalia negação lógica (!) materializando 0 ou 1 em registrador
        if action == "not_reg":
            src = self._emit_choice(node.operand, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Seqz(dst, src, origin=node.span))
            return dst

        # Avalia negação lógica (!) em fluxo de controle trocando os rótulos de destino
        if action == "not_cond":
            self._emit_choice(node.operand, COND, table, true_label=false_label, false_label=true_label)
            return None

        # Avalia operador lógico E (&&) em fluxo de controle
        if action == "and_cond":
            mid_label = self.ctx.label()
            # Avalia o operando esquerdo: se falso, aborta direto para false_label (curto-circuito);
            # se verdadeiro, avança para mid_label onde o operando direito decide o destino final.
            self._emit_choice(node.left, COND, table, true_label=mid_label, false_label=false_label)
            self.ctx.emit(I.LabelInstr(mid_label, origin=node.right.span))
            self._emit_choice(node.right, COND, table, true_label=true_label, false_label=false_label)
            return None

        # Avalia operador lógico OU (||) em fluxo de controle
        if action == "or_cond":
            mid_label = self.ctx.label()
            # Avalia o operando esquerdo: se verdadeiro, salta direto para true_label (curto-circuito);
            # se falso, segue para mid_label onde o operando direito é avaliado.
            self._emit_choice(node.left, COND, table, true_label=true_label, false_label=mid_label)
            self.ctx.emit(I.LabelInstr(mid_label, origin=node.right.span))
            self._emit_choice(node.right, COND, table, true_label=true_label, false_label=false_label)
            return None

        # Avalia operador lógico E (&&) materializando o resultado booleano em registrador
        if action == "and_reg":
            dst = self.ctx.temp()
            mid_label = self.ctx.label()
            true_l = self.ctx.label()
            false_l = self.ctx.label()
            end_l = self.ctx.label()

            # Avalia ambos os operandos com curto-circuito; se ambos forem verdadeiros, cai em true_l,
            # carrega 1 em dst e pula para end_l; caso contrário, cai em false_l e carrega 0 em dst.
            self._emit_choice(node.left, COND, table, true_label=mid_label, false_label=false_l)
            self.ctx.emit(I.LabelInstr(mid_label, origin=node.right.span))
            self._emit_choice(node.right, COND, table, true_label=true_l, false_label=false_l)

            self.ctx.emit(I.LabelInstr(true_l, origin=node.span))
            self.ctx.emit(I.Li(dst, 1, origin=node.span))
            self.ctx.emit(I.Jump(end_l, origin=node.span))

            self.ctx.emit(I.LabelInstr(false_l, origin=node.span))
            self.ctx.emit(I.Li(dst, 0, origin=node.span))
            self.ctx.emit(I.LabelInstr(end_l, origin=node.span))
            return dst

        # Avalia operador lógico OU (||) materializando o resultado booleano em registrador
        if action == "or_reg":
            dst = self.ctx.temp()
            mid_label = self.ctx.label()
            true_l = self.ctx.label()
            false_l = self.ctx.label()
            end_l = self.ctx.label()

            # Avalia os operandos com curto-circuito; se qualquer um for verdadeiro, vai para true_l,
            # carrega 1 em dst e salta ao fim; se ambos forem falsos, cai em false_l e carrega 0 em dst.
            self._emit_choice(node.left, COND, table, true_label=true_l, false_label=mid_label)
            self.ctx.emit(I.LabelInstr(mid_label, origin=node.right.span))
            self._emit_choice(node.right, COND, table, true_label=true_l, false_label=false_l)

            self.ctx.emit(I.LabelInstr(true_l, origin=node.span))
            self.ctx.emit(I.Li(dst, 1, origin=node.span))
            self.ctx.emit(I.Jump(end_l, origin=node.span))

            self.ctx.emit(I.LabelInstr(false_l, origin=node.span))
            self.ctx.emit(I.Li(dst, 0, origin=node.span))
            self.ctx.emit(I.LabelInstr(end_l, origin=node.span))
            return dst

        # Avalia literal booleano usado diretamente como condição de salto
        if action == "bool_literal_cond":
            # Avalia se o literal é verdadeiro para saltar ao rótulo true_label ou false_label
            if node.value:
                self.ctx.emit(I.Jump(true_label, origin=node.span))
            else:
                self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        # Avalia variável booleana usada diretamente como condição de salto
        if action == "bool_identif_cond":
            reg = self.ctx.variable(node.metadata["symbol"])
            self.ctx.emit(I.Bnez(reg, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        # 4.6. Chamadas de Função
        # Avalia chamada de função cujo retorno será armazenado em registrador
        if action == "call_reg":
            arg_regs = [self._emit_choice(arg, REG, table) for arg in node.arguments]
            func_symbol = node.metadata["symbol"]
            dst = self.ctx.temp()
            self.ctx.emit(I.Call(dst, func_symbol, arg_regs, origin=node.span))
            return dst

        # Avalia chamada de função executada apenas por efeito colateral (sem retorno)
        if action == "call_effect":
            arg_regs = [self._emit_choice(arg, REG, table) for arg in node.arguments]
            func_symbol = node.metadata["symbol"]
            self.ctx.emit(I.Call(None, func_symbol, arg_regs, origin=node.span))
            return None

        # Avalia chamada de função usada diretamente como condição de desvio
        if action == "call_cond":
            # Avalia os argumentos, executa a chamada guardando o retorno em dst, testa se dst != 0
            # via Bnez para saltar ao true_label ou segue para false_label caso contrário.
            arg_regs = [self._emit_choice(arg, REG, table) for arg in node.arguments]
            func_symbol = node.metadata["symbol"]
            dst = self.ctx.temp()
            self.ctx.emit(I.Call(dst, func_symbol, arg_regs, origin=node.span))
            self.ctx.emit(I.Bnez(dst, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        raise ValueError(f"Ação desconhecida: {action}")