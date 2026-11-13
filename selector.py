"""Ponto de implementação do reconhecimento de padrões e custos mínimos."""

from patterns import *


class Selector:
    """Selecione coberturas sem executar expressões ou emitir instruções."""

    def __init__(self, rules):
        # Armazena as regras de transformação/padrão que o seletor pode aplicar
        self.rules = tuple(rules)

    def analyze(self, expr):
        """Calcule mínimos por nó/classe sem emitir instruções."""

        # Tabela de Programação Dinâmica (Memoization) para armazenar 
        # a escolha de menor custo para cada par (nó, classe_resultado).
        tabela = SelectionTable()

        def match_rule_to_node(rule, current_node):
            """
            Verifica se o padrão de uma regra específica 'encaixa' no nó atual.
            Retorna uma lista de subproblemas (filhos e o que se espera deles) 
            ou None caso a regra não sirva.
            """
            rule_pattern = rule.pattern

            # 1. Verifica se o tipo/classe do nó confere com o esperado pelo padrão
            if rule_pattern.kind is not None and not isinstance(current_node, rule_pattern.kind):
                return None

            # 2. Verifica se o operador lógico/aritmético confere
            if rule_pattern.operator is not None:
                if getattr(current_node, "operator", None) != rule_pattern.operator:
                    return None

            # 3. Verifica condições (predicados) customizados da regra
            if rule_pattern.predicate is not None and not rule_pattern.predicate(current_node):
                return None

            # Obtém os nós filhos do nó atual na árvore de expressão
            node_children = children(current_node)

            # Se a regra exige que não haja filhos (nó folha), mas existem filhos, falha
            if rule_pattern.predicate is not None and not rule_pattern.children:
                return () 

            # 4. Tratamento de múltiplos argumentos genéricos (ex: listas de parâmetros)
            # Se o padrão exige apenas 1 filho do tipo 'Args', ele aceita todos os filhos do nó
            if (len(rule_pattern.children) == 1 and isinstance(rule_pattern.children[0], Args)):
                result_class = rule_pattern.children[0].result
                # Mapeia todos os filhos para a mesma classe de resultado esperada
                return tuple((child, result_class) for child in node_children)

            # 5. Tratamento de correspondência exata de filhos
            # A quantidade de filhos do nó deve ser exatamente igual à quantidade exigida pela regra
            if len(node_children) != len(rule_pattern.children):
                return None

            matched_subproblems = []

            # Mapeia cada filho do nó à exigência específica (Need) da regra
            for child, requirement in zip(node_children, rule_pattern.children):
                if not isinstance(requirement, Need):
                    return None
                matched_subproblems.append((child, requirement.result))

            return tuple(matched_subproblems)

        
        def visit(current_node):
            """
            Percorre a árvore de expressões de baixo para cima (pós-ordem / bottom-up).
            Isso garante que os custos dos filhos já estejam calculados na 'tabela' 
            antes de calcularmos o custo do nó pai.
            """
            if current_node is None:
                return

            # Primeiro, visita recursivamente todos os filhos (Bottom-Up)
            for child in children(current_node):
                visit(child)

            # Em seguida, avalia todas as regras possíveis para o nó atual
            for rule in self.rules:

                # Verifica se a regra atual pode ser aplicada a este nó
                match_subproblems = match_rule_to_node(rule, current_node)

                # Se não encaixar, pula para a próxima regra
                if match_subproblems is None:
                    continue

                # Inicia o custo com o custo intrínseco da regra sendo avaliada
                total_cost = rule.cost
                all_subproblems_covered = True

                # Soma o custo ótimo (já calculado) de cada filho avaliado
                for child, result_class in match_subproblems:
                    # Consulta a tabela para ver se o filho conseguiu resolver sua dependência
                    child_choice = tabela.lookup(child, result_class)

                    # Se algum filho não tiver cobertura para a classe necessária, esta regra falha
                    if child_choice is None:
                        all_subproblems_covered = False
                        break

                    # Acumula o custo da subárvore
                    total_cost += child_choice.cost

                # Se falhou em cobrir algum filho, descarta esta regra
                if not all_subproblems_covered:
                     continue

                # Agora verifica se este é o MELHOR custo encontrado até agora para o nó atual
                current_choice = tabela.lookup(current_node, rule.result)

                # Se ainda não havia escolha (None) ou se a nova escolha é mais barata
                if current_choice is None or total_cost < current_choice.cost:
                    # Cria a nova escolha ótima e atualiza a tabela de programação dinâmica
                    new_choice = Choice(total_cost, rule, match_subproblems)
                    tabela.put(current_node, rule.result, new_choice)

        # Inicia a travessia e o cálculo pela raiz da expressão
        visit(expr)
        
        # Retorna a tabela completa com as melhores escolhas em todos os nós
        return tabela