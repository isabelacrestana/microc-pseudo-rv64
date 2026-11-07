"""Ponto de implementação do reconhecimento de padrões e custos mínimos."""

from patterns import *


class Selector:
    """Selecione coberturas sem executar expressões ou emitir instruções."""

    def __init__(self, rules):
        self.rules = tuple(rules)

    def analyze(self, expr):
        """Calcule mínimos por nó/classe sem emitir instruções."""

        tabela = SelectionTable()

        def match_rule_to_node(rule,current_node):
            rule_pattern = rule.pattern

            if rule_pattern.kind is not None and not isinstance(current_node, rule_pattern.kind):
                return None

            if rule_pattern.operator is not None:
                if getattr(current_node, "operator", None) != rule_pattern.operator:
                    return None

            if rule_pattern.predicate is not None and not rule_pattern.predicate(current_node):
                return None

            node_children = children(current_node)

            if rule_pattern. predicate is not None and not rule_pattern.children:
                return() 

            if ( len(rule_pattern.children) == 1 and isinstance(rule_pattern.children[0], Args)):
                result_class = rule_pattern.children[0].result

                return tuple((child, result_class) for child in node_children)

            if len(node_children) != len(rule_pattern.children):
                return None

            matched_subproblems = []

            for child, requirement in zip(node_children, rule_pattern.children):
                if not isinstance(requirement, Need):
                    return None

                matched_subproblems.append((child, requirement.result))

            return tuple(matched_subproblems)

        
        def visit(current_node):

            if current_node is None:
                return


            for child in children(current_node):
                visit(child)

            for rule in self.rules:

                match_subproblems = match_rule_to_node(rule, current_node)

                if match_subproblems is None:
                    continue

                total_cost = rule.cost
                all_subproblems_covered = True

                for child, result_class in match_subproblems:
                    child_choice = tabela.lookup(child, result_class)

                    if child_choice is None:
                        all_subproblems_covered = False
                        break

                    total_cost += child_choice.cost

                if not all_subproblems_covered:
                     continue

                current_choice = tabela.lookup(current_node, rule.result)

                if current_choice is None or total_cost < current_choice.cost:
                    new_choice = Choice(total_cost,rule, match_subproblems)
                    tabela.put(current_node, rule.result, new_choice)

        visit(expr)
        return tabela


