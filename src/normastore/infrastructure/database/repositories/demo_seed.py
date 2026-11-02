from normastore.domain.enums import CopyStatus
from normastore.infrastructure.database.models import Customer, Employee, Order, PhysicalCopy


class DemoSeedRepository:
    def __init__(self, session):
        self.session = session

    def sample_customers(self):
        return self.session.query(Customer).filter(Customer.full_name.like("Khách hàng mẫu %"))

    def sample_employees(self):
        return self.session.query(Employee).filter(Employee.full_name.like("Nhân viên mẫu %"))

    def customer_count(self):
        return self.session.query(Customer).count()

    def employee_count(self):
        return self.session.query(Employee).count()

    def customers(self):
        return self.session.query(Customer).all()

    def employees(self):
        return self.session.query(Employee).all()

    def available_copies(self):
        return (
            self.session.query(PhysicalCopy)
            .filter(PhysicalCopy.status == CopyStatus.AVAILABLE)
            .all()
        )

    def order_count(self):
        return self.session.query(Order).count()

    def add_customer(self, customer):
        self.session.add(customer)

    def add_employee(self, employee):
        self.session.add(employee)

    def add_order(self, order):
        self.session.add(order)
        self.session.flush()

    def add_order_line(self, line):
        self.session.add(line)
        self.session.flush()

    def add_rental_term(self, term):
        self.session.add(term)

    def add_payment(self, payment):
        self.session.add(payment)
