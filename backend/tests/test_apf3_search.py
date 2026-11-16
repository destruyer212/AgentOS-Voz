from apf3.search import SEARCH_ALGORITHMS, OrderCompletionProblem


def test_all_search_algorithms_reach_valid_order_completion():
    problem = OrderCompletionProblem()

    for algorithm in SEARCH_ALGORITHMS.values():
        result = algorithm(problem)

        assert result is not None
        assert set(result.path) == problem.goal_state - problem.initial_state
        assert result.cost == len(result.path)
        assert result.expanded > 0


def test_search_problem_requires_items_and_fulfillment_before_confirmation():
    problem = OrderCompletionProblem()

    successors = list(problem.successors(problem.initial_state))

    assert {action for action, _, _ in successors} == {"fulfillment"}
