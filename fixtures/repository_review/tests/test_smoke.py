from review_target import Account, parse_enabled


def test_smoke_behaviour_only():
    account = Account("A", 100)
    account.withdraw(20)
    assert account.balance_cents == 80
    assert parse_enabled("yes")
