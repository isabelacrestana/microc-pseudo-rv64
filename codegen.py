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

            for index, param in enumerate(func_declaration.parameters):
                param_symbol = param.metadata["symbol"]
                dst_reg = self.ctx.variable(param_symbol)
                self.ctx.emit(I.Param(dst_reg, index, origin=param.span))

            self.statement(func_declaration.body)

            if func_symbol.type == TypeName.VOID or getattr(func_declaration, "return_type", None) == TypeName.VOID:
                if not func_ir.instructions or not isinstance(func_ir.instructions[-1], I.Return):
                    self.ctx.emit(I.Return(None, origin=func_declaration.span))

        return program_ir

    def statement(self, node):
        """Traduza um comando ad hoc."""
        if isinstance(node, Block):
            for stmt in node.statements:
                self.statement(stmt)

        elif isinstance(node, VarDecl):
            if node.initializer is not None:
                val_reg = self.expression(node.initializer, REG)
                var_reg = self.ctx.variable(node.metadata["symbol"])
                self.ctx.emit(I.Move(var_reg, val_reg, origin=node.span))
            else:
                self.ctx.variable(node.metadata["symbol"])

        elif isinstance(node, Assignment):
            val_reg = self.expression(node.value, REG)
            symbol = node.target.metadata.get("symbol") or node.metadata.get("symbol")
            var_reg = self.ctx.variable(symbol)
            self.ctx.emit(I.Move(var_reg, val_reg, origin=node.span))

        elif isinstance(node, CallStmt):
            self.expression(node.call, EFFECT)

        elif isinstance(node, ReturnStmt):
            if node.value is None:
                self.ctx.emit(I.Return(None, origin=node.span))
            else:
                val_reg = self.expression(node.value, REG)
                self.ctx.emit(I.Return(val_reg, origin=node.span))

        elif isinstance(node, IfStmt):
            if node.else_block is None:
                then_label = self.ctx.label()
                end_label = self.ctx.label()

                self.expression(node.condition, COND, true_label=then_label, false_label=end_label)
                self.ctx.emit(I.LabelInstr(then_label, origin=node.then_block.span))
                self.statement(node.then_block)
                self.ctx.emit(I.LabelInstr(end_label, origin=node.span))
            else:
                then_label = self.ctx.label()
                else_label = self.ctx.label()
                end_label = self.ctx.label()

                self.expression(node.condition, COND, true_label=then_label, false_label=else_label)
                self.ctx.emit(I.LabelInstr(then_label, origin=node.then_block.span))
                self.statement(node.then_block)
                self.ctx.emit(I.Jump(end_label, origin=node.span))
                self.ctx.emit(I.LabelInstr(else_label, origin=node.else_block.span))
                self.statement(node.else_block)
                self.ctx.emit(I.LabelInstr(end_label, origin=node.span))

        elif isinstance(node, WhileStmt):
            start_label = self.ctx.label()
            body_label = self.ctx.label()
            end_label = self.ctx.label()

            self.ctx.emit(I.LabelInstr(start_label, origin=node.span))
            self.expression(node.condition, COND, true_label=body_label, false_label=end_label)
            self.ctx.emit(I.LabelInstr(body_label, origin=node.body.span))
            self.statement(node.body)
            self.ctx.emit(I.Jump(start_label, origin=node.span))
            self.ctx.emit(I.LabelInstr(end_label, origin=node.span))

        elif isinstance(node, PrintStmt):
            for item in node.items:
                if isinstance(item, StringLiteral):
                    ref = self.ctx.string(item.value)
                    self.ctx.emit(I.PrintString(ref, origin=item.span))
                else:
                    val_reg = self.expression(item, REG)
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
        if choice is None:
            raise ValueError(f"Sem cobertura para {result_class} no nó em {node.span}")
        return self._emit_choice(node, result_class, table, true_label=true_label, false_label=false_label)

    def _emit_choice(self, node, result_class, table, true_label=None, false_label=None):
        choice = table.lookup(node, result_class)
        if choice is None:
            raise ValueError(f"Sem cobertura para {result_class} no nó em {node.span}")

        action = choice.rule.action

        # 4.1. Folhas e Literais
        if action == "li_int":
            dst = self.ctx.temp()
            self.ctx.emit(I.Li(dst, node.value, origin=node.span))
            return dst

        if action == "li_bool":
            dst = self.ctx.temp()
            self.ctx.emit(I.Li(dst, int(node.value), origin=node.span))
            return dst

        if action == "identifier":
            return self.ctx.variable(node.metadata["symbol"])

        if action == "imm12":
            return signed_literal(node)

        if action == "pow2":
            lit = signed_literal(node)
            return lit.bit_length() - 1

        # 4.2. Operações Aritméticas (REG)
        if action == "neg":
            src = self._emit_choice(node.operand, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Neg(dst, src, origin=node.span))
            return dst

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

        if action == "addi_right":
            lhs = self._emit_choice(node.left, REG, table)
            imm = self._emit_choice(node.right, IMM12, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Addi(dst, lhs, imm, origin=node.span))
            return dst

        if action == "addi_left":
            imm = self._emit_choice(node.left, IMM12, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Addi(dst, rhs, imm, origin=node.span))
            return dst

        if action == "sub_imm_right":
            lhs = self._emit_choice(node.left, REG, table)
            imm = -signed_literal(node.right)
            dst = self.ctx.temp()
            self.ctx.emit(I.Addi(dst, lhs, imm, origin=node.span))
            return dst

        if action == "slli_right":
            lhs = self._emit_choice(node.left, REG, table)
            shift = self._emit_choice(node.right, POW2, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slli(dst, lhs, shift, origin=node.span))
            return dst

        if action == "slli_left":
            shift = self._emit_choice(node.left, POW2, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slli(dst, rhs, shift, origin=node.span))
            return dst

        # 4.3. Comparações para Valor Booleano (REG)
        if action == "slt":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slt(dst, lhs, rhs, origin=node.span))
            return dst

        if action == "sgt":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slt(dst, rhs, lhs, origin=node.span))
            return dst

        if action == "sle":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slt(dst, rhs, lhs, origin=node.span))
            self.ctx.emit(I.Seqz(dst, dst, origin=node.span))
            return dst

        if action == "sge":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Slt(dst, lhs, rhs, origin=node.span))
            self.ctx.emit(I.Seqz(dst, dst, origin=node.span))
            return dst

        if action == "seq":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Xor(dst, lhs, rhs, origin=node.span))
            self.ctx.emit(I.Seqz(dst, dst, origin=node.span))
            return dst

        if action == "sne":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Xor(dst, lhs, rhs, origin=node.span))
            self.ctx.emit(I.Snez(dst, dst, origin=node.span))
            return dst

        # 4.4. Comparações Diretas para Controle (COND)
        if action == "branch_lt":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Blt(lhs, rhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        if action == "branch_ge":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Bge(lhs, rhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        if action == "branch_gt":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Blt(rhs, lhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        if action == "branch_le":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Bge(rhs, lhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        if action == "branch_eq":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Beq(lhs, rhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        if action == "branch_ne":
            lhs = self._emit_choice(node.left, REG, table)
            rhs = self._emit_choice(node.right, REG, table)
            self.ctx.emit(I.Bne(lhs, rhs, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        # 4.5. Operadores Lógicos, Curto-Circuito e Folhas Booleanas
        if action == "not_reg":
            src = self._emit_choice(node.operand, REG, table)
            dst = self.ctx.temp()
            self.ctx.emit(I.Seqz(dst, src, origin=node.span))
            return dst

        if action == "not_cond":
            self._emit_choice(node.operand, COND, table, true_label=false_label, false_label=true_label)
            return None

        if action == "and_cond":
            mid_label = self.ctx.label()
            self._emit_choice(node.left, COND, table, true_label=mid_label, false_label=false_label)
            self.ctx.emit(I.LabelInstr(mid_label, origin=node.right.span))
            self._emit_choice(node.right, COND, table, true_label=true_label, false_label=false_label)
            return None

        if action == "or_cond":
            mid_label = self.ctx.label()
            self._emit_choice(node.left, COND, table, true_label=true_label, false_label=mid_label)
            self.ctx.emit(I.LabelInstr(mid_label, origin=node.right.span))
            self._emit_choice(node.right, COND, table, true_label=true_label, false_label=false_label)
            return None

        if action == "and_reg":
            dst = self.ctx.temp()
            mid_label = self.ctx.label()
            true_l = self.ctx.label()
            false_l = self.ctx.label()
            end_l = self.ctx.label()

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

        if action == "or_reg":
            dst = self.ctx.temp()
            mid_label = self.ctx.label()
            true_l = self.ctx.label()
            false_l = self.ctx.label()
            end_l = self.ctx.label()

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

        if action == "bool_literal_cond":
            if node.value:
                self.ctx.emit(I.Jump(true_label, origin=node.span))
            else:
                self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        if action == "bool_identif_cond":
            reg = self.ctx.variable(node.metadata["symbol"])
            self.ctx.emit(I.Bnez(reg, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        # 4.6. Chamadas de Função
        if action == "call_reg":
            arg_regs = [self._emit_choice(arg, REG, table) for arg in node.arguments]
            func_symbol = node.metadata["symbol"]
            dst = self.ctx.temp()
            self.ctx.emit(I.Call(dst, func_symbol, arg_regs, origin=node.span))
            return dst

        if action == "call_effect":
            arg_regs = [self._emit_choice(arg, REG, table) for arg in node.arguments]
            func_symbol = node.metadata["symbol"]
            self.ctx.emit(I.Call(None, func_symbol, arg_regs, origin=node.span))
            return None

        if action == "call_cond":
            arg_regs = [self._emit_choice(arg, REG, table) for arg in node.arguments]
            func_symbol = node.metadata["symbol"]
            dst = self.ctx.temp()
            self.ctx.emit(I.Call(dst, func_symbol, arg_regs, origin=node.span))
            self.ctx.emit(I.Bnez(dst, true_label, origin=node.span))
            self.ctx.emit(I.Jump(false_label, origin=node.span))
            return None

        raise ValueError(f"Ação desconhecida: {action}")
