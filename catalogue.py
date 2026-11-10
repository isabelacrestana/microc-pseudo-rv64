"""Ponto de implementação das regras declarativas do enunciado."""
import load_previous                                                                                                                                  
from ast_nodes import (                                                                                                                               
    BinaryExpr,                                                                                                                                       
    BinaryOperator,                                                                                                                                   
    BoolLiteral,                                                                                                                                      
    CallExpr,                                                                                                                                         
    IdentifierExpr,                                                                                                                                   
    IntLiteral,                                                                                                                                       
    UnaryExpr,                                                                                                                                        
    UnaryOperator,                                                                                                                                    
)                                                                                                                                                     
from patterns import (                                                                                                                                
    COND,                                                                                                                                             
    EFFECT,                                                                                                                                           
    IMM12,                                                                                                                                            
    POW2,                                                                                                                                             
    REG,                                                                                                                                              
    Args,
    Need,
    Pattern,
    Rule,
    imm12,
    neg_imm12,
    pow2,
)


def catalogue():
    """Codifique o catálogo do enunciado com Rule e Pattern."""


    rules = [
            # 1. Literais para REG
            Rule("int_literal", REG, Pattern(IntLiteral), 1, "li_int"),
            Rule("bool_literal", REG, Pattern(BoolLiteral), 1, "li_bool"),
  
            # 2. Identificador para REG
            Rule("identifier", REG, Pattern(IdentifierExpr), 0, "identifier"),
  
            # 3. Literais elegíveis para IMM12 e POW2
            Rule("imm12", IMM12, Pattern(predicate=imm12), 0, "imm12"),
            Rule("pow2", POW2, Pattern(predicate=pow2), 0, "pow2"),
  
            # 4. Negação aritmética (Ex: -x)
            Rule("neg_reg", REG, Pattern(UnaryExpr, UnaryOperator.NEGATE, (Need(REG),)), 1, "neg"),

            # 5. Operações aritméticas
            Rule("add_reg", REG, Pattern(BinaryExpr, BinaryOperator.ADD, (Need(REG), Need(REG)) ), 1, "add"),
            Rule("sub_reg", REG, Pattern(BinaryExpr, BinaryOperator.SUBTRACT, (Need(REG), Need(REG)) ), 1, "sub"),
            Rule("mul_reg", REG, Pattern(BinaryExpr, BinaryOperator.MULTIPLY, (Need(REG), Need(REG)) ), 1, "mul"),
            Rule("div_reg", REG, Pattern(BinaryExpr, BinaryOperator.DIVIDE, (Need(REG), Need(REG)) ), 1, "div"),
            # resto da divisão
            Rule("rem_div", REG, 
                 Pattern(BinaryExpr, BinaryOperator.REMAINDER, (Need(REG), Need(REG)) ),
                 1, "rem"),
                            
            # 6. Soma com imediato
            # imediato na direita
            Rule("add_imed_right_reg", REG, 
                 Pattern(BinaryExpr, BinaryOperator.ADD, (Need(REG), Need(IMM12)) ),
                 1, "addi_right"),
            # imediato na esquerda
            Rule("add_imed_left_reg", REG, 
                 Pattern(BinaryExpr, BinaryOperator.ADD, (Need(IMM12), Need(REG)) ),
                 1, "addi_left"),

            
            # 7. Subtração imediato direita (x - c onde -c cabe no imediato)
            Rule("sub_imm_right_reg", REG,
                Pattern(BinaryExpr, BinaryOperator.SUBTRACT, (Need(REG), None), predicate=lambda n: neg_imm12(n.right)),
                1, "sub_imm_right"),

            # 8. Multiplicação por potência de 2:
            # x * 2^k (pot2 na direita)
            Rule("mul_pow_2_right_reg", REG, 
                  Pattern(BinaryExpr, BinaryOperator.MULTIPLY, (Need(REG), Need(POW2))),
                  1, "slli_right"),

            # 2^k * x (pot2 na esquerda)
            Rule("mul_pow_2_left_reg", REG,
                 Pattern(BinaryExpr, BinaryOperator.MULTIPLY, (Need(POW2), Need(REG)) ),
                 1, "slli_left"),

            # 9. Comparações (< e >)
            Rule("lt_reg", REG,
                 Pattern(BinaryExpr, BinaryOperator.LESS, (Need(REG), Need(REG))),
                 1, "slt"),
            Rule("gt_reg", REG,
                 Pattern(BinaryExpr, BinaryOperator.GREATER, (Need(REG), Need(REG))),
                 1, "sgt"),

            # 10. Menor e maior igual (Custo 2: emite Slt + Seqz, pois RISC-V não possui instrução direta)
            Rule("le_reg", REG,
                 Pattern(BinaryExpr, BinaryOperator.LESS_EQUAL, (Need(REG), Need(REG))),
                 2, "sle"),
            Rule("ge_reg", REG,
                 Pattern(BinaryExpr, BinaryOperator.GREATER_EQUAL, (Need(REG), Need(REG))),
                 2, "sge"), 

            # 11. Comparação de igual e diferente (Custo 2: emite Xor + Seqz/Snez para testar contra zero)    
            Rule("eq_reg", REG,
                 Pattern(BinaryExpr, BinaryOperator.EQUAL, (Need(REG), Need(REG))),
                 2, "seq"),
            Rule("ne_reg", REG,
                 Pattern(BinaryExpr, BinaryOperator.NOT_EQUAL, (Need(REG), Need(REG))),
                 2, "sne"),

            # 12. Condições para salto (adicionadas no loop abaixo com custo 2)

            # 13. Negação lógica como valor
            Rule("not_reg", REG,
                 Pattern(UnaryExpr, UnaryOperator.NOT, (Need(REG),)),
                 1, "not_reg"),
        
            # 14. Negação lógica como condição
            Rule("not_cond", COND,
                 Pattern(UnaryExpr, UnaryOperator.NOT, (Need(COND),)),
                 0, "not_cond"),

            # 15. And e Or como condicões de salto
            Rule("and_cond", COND,
                 Pattern(BinaryExpr, BinaryOperator.LOGICAL_AND, (Need(COND), Need(COND))),
                 0, "and_cond"),
            Rule("or_cond", COND,
                 Pattern(BinaryExpr, BinaryOperator.LOGICAL_OR, (Need(COND), Need(COND))),
                 0, "or_cond"),

            # 16. And e Or como valor (Custo 3: emite duas cargas Li de 1 e 0 + Jump de convergência)
            Rule("and_reg", REG,
                 Pattern(BinaryExpr, BinaryOperator.LOGICAL_AND, (Need(COND), Need(COND))),
                 3, "and_reg"),
            Rule("or_reg", REG,
                 Pattern(BinaryExpr, BinaryOperator.LOGICAL_OR, (Need(COND), Need(COND))),
                 3, "or_reg"),

            # 17. Literal booleano como condição
            Rule("bool_literal_cond", COND,
                 Pattern(BoolLiteral),
                 1, "bool_literal_cond"),

            # 18. Indentificador booleano como condição (Custo 2: emite Bnez para true_label + Jump para false_label)
            Rule("bool_identif_cond", COND,
                 Pattern(IdentifierExpr),
                 2, "bool_identif_cond"),

            # 19. Chamada com argumentos REG para REG ou EFFECT
            Rule("call_reg", REG, Pattern(CallExpr, children=(Args(REG),)), 1, "call_reg"),
            Rule("call_effect", EFFECT, Pattern(CallExpr, children=(Args(REG),)), 1, "call_effect"),
        
            # 20. Chamada bool como condição (Custo 3: emite Call + Bnez para true_label + Jump para false_label)
            Rule("call_cond", COND, Pattern(CallExpr, children=(Args(REG),)), 3, "call_cond"),

        ]

    # 12. Mapeamento do operador para o nome/ação (Custo 2: Branch condicional + Jump para false_label)
    relational_ops = [
        (BinaryOperator.LESS, "lt"),
        (BinaryOperator.LESS_EQUAL, "le"),
        (BinaryOperator.GREATER, "gt"),
        (BinaryOperator.GREATER_EQUAL, "ge"),
        (BinaryOperator.EQUAL, "eq"),
        (BinaryOperator.NOT_EQUAL, "ne"),
    ]
  
    for op, name in relational_ops:
        rules.append(
            Rule(
                f"cmp_{name}_cond",
                COND,
                Pattern(BinaryExpr, op, (Need(REG), Need(REG))),
                2,
                f"branch_{name}",
            )
        )
  

    return rules
