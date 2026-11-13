"""Pontos de implementação da geração de comandos e expressões."""

import load_previous
from ir import Context, ProgramIR, FunctionIR
from selector import Selector
from catalogue import catalogue
from ast_nodes import TypeName

import ir as I

class CodeGenerator:
    """Coordene comandos ad hoc e seleção de expressões com DP."""

    def generate(self, program):
        """Traduza funções e comandos. Selecione expressões com DP."""

        program_ir = ProgramIR()
        self.selector = Selector(catalogue())

        for func_declaration in program.functions:

            func_symbol = func_declaration.metadata['symbol']
            func_ir = FunctionIR(func_symbol)
            program_ir.functions.append(func_ir)

            self.ctx = Context(func_ir, program_ir)

            for index, param in enumerate(func_declaration.parameters):
                param_symbol = param.metadata["symbol"]
                dst_reg = self.ctx.variable(param_symbol)
                self.ctx.emit(I.Param(dst_reg, index, origin=param.span))

            self.statement(func_declaration.body)

            if func_declaration.return_type == TypeName.VOID:
                if not func_ir.instructions or not isinstance(func_ir.instructions[-1], I.Return):
                    self.ctx.emit(I.Return(None, origin=func_declaration.span))

        return program_ir


        
        raise NotImplementedError("implemente CodeGenerator.generate")

    def expression(self, node, result_class, true_label=None, false_label=None):
        """Selecione e reconstrua uma expressão, preservando curto-circuito."""
        raise NotImplementedError("implemente seleção e emissão")

    def statement(self, node):
        """Traduza um comando ad hoc."""
        raise NotImplementedError("implemente comandos")
