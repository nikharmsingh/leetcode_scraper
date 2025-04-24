from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from bson.objectid import ObjectId

class User(UserMixin):
    def __init__(self, username, email, password=None, _id=None):
        self.username = username
        self.email = email
        self._id = _id
        if password:
            self.set_password(password)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self._id) if self._id else None

    @staticmethod
    def from_dict(data):
        user = User(
            username=data['username'],
            email=data['email'],
            _id=data['_id']
        )
        user.password_hash = data['password_hash']
        return user

    def to_dict(self):
        return {
            'username': self.username,
            'email': self.email,
            'password_hash': self.password_hash
        }

class SolvedProblem:
    def __init__(self, user_id, problem_id, solved=False, _id=None):
        self.user_id = user_id
        self.problem_id = problem_id
        self.solved = solved
        self._id = _id
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    @staticmethod
    def from_dict(data):
        problem = SolvedProblem(
            user_id=data['user_id'],
            problem_id=data['problem_id'],
            solved=data['solved'],
            _id=data['_id']
        )
        problem.created_at = data['created_at']
        problem.updated_at = data['updated_at']
        return problem

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'problem_id': self.problem_id,
            'solved': self.solved,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        } 