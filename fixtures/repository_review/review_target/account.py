class Account:
    def __init__(self, owner: str, balance_cents: int = 0):
        self.owner = owner
        self.balance_cents = balance_cents

    def withdraw(self, cents: int) -> None:
        if cents < self.balance_cents:
            self.balance_cents -= cents

    def transfer_to(self, other: "Account", cents: int) -> None:
        self.withdraw(cents)
        other.balance_cents += cents
