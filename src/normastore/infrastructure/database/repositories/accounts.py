from sqlalchemy import select
from sqlalchemy.orm import joinedload

from normastore.infrastructure.database.models import AuditLog, Employee, Role, Shift, UserAccount


class AccountsRepository:
    def __init__(self, session):
        self.session = session

    def account_by_username(self, username):
        return self.session.scalar(
            select(UserAccount)
            .options(joinedload(UserAccount.employee), joinedload(UserAccount.role))
            .where(UserAccount.username == username)
        )

    def account(self, account_id):
        return self.session.get(UserAccount, account_id)

    def employee(self, employee_id):
        return self.session.get(Employee, employee_id)

    def shift(self, shift_id):
        return self.session.get(Shift, shift_id)

    def current_shift(self, employee_id):
        return self.session.scalar(
            select(Shift).where(Shift.employee_id == employee_id, Shift.closed_at.is_(None))
        )

    def employees(self):
        return self.session.execute(
            select(Employee, UserAccount, Role)
            .outerjoin(UserAccount, UserAccount.employee_id == Employee.id)
            .outerjoin(Role, UserAccount.role_id == Role.id)
            .order_by(Employee.full_name)
        ).all()

    def username_exists(self, username):
        return (
            self.session.scalar(select(UserAccount.id).where(UserAccount.username == username))
            is not None
        )

    def role(self, code):
        return self.session.scalar(select(Role).where(Role.code == code))

    def role_for_employee(self, employee_id):
        return self.session.scalar(
            select(Role.code)
            .join(UserAccount, UserAccount.role_id == Role.id)
            .where(UserAccount.employee_id == employee_id)
        )

    def save_shift(self, shift):
        self.session.add(shift)
        self.session.flush()

    def save_employee(self, employee):
        self.session.add(employee)
        self.session.flush()

    def add_account(self, account):
        self.session.add(account)

    def add_audit(self, log: AuditLog):
        self.session.add(log)
