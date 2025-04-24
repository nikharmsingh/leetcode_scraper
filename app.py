from flask import Flask, render_template, jsonify, redirect, url_for, request, send_from_directory, session, flash
import requests
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv
import time
import json
import re
from urllib.parse import urlencode
from models import db, User, SolvedProblem
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from functools import wraps
import math

# Get the absolute path to the current directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'),
            static_url_path='')

# Load environment variables
load_dotenv()

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///leetcode.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Create database tables
with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def login_required_json(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'status': 'error', 'message': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('problems'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
            
        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return redirect(url_for('register'))
            
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('problems'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('problems'))
            
        flash('Invalid username or password')
        return redirect(url_for('login'))
        
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/problems')
@login_required
def problems():
    return render_template('problems.html')

@app.route('/toggle-solved', methods=['POST'])
@login_required_json
def toggle_solved():
    try:
        data = request.get_json()
        problem_id = data.get('problem_id')
        solved = data.get('solved')
        
        if not problem_id:
            return jsonify({'status': 'error', 'message': 'Problem ID is required'}), 400
            
        # Check if problem already exists for user
        solved_problem = SolvedProblem.query.filter_by(
            user_id=current_user.id,
            problem_id=problem_id
        ).first()
        
        if solved_problem:
            solved_problem.solved = solved
        else:
            solved_problem = SolvedProblem(
                user_id=current_user.id,
                problem_id=problem_id,
                solved=solved
            )
            db.session.add(solved_problem)
            
        db.session.commit()
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/scrape-leetcode')
def scrape_leetcode():
    try:
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        search = request.args.get('search', '')
        difficulty = request.args.get('difficulty', '')

        # Calculate offset for pagination
        offset = (page - 1) * per_page

        # Prepare GraphQL variables
        variables = {
            "categorySlug": "",
            "skip": offset,
            "limit": per_page,
            "filters": {}
        }

        if difficulty:
            variables["filters"]["difficulty"] = difficulty.upper()

        if search:
            variables["searchQuery"] = search

        # Make the request to LeetCode API
        response = requests.post(
            'https://leetcode.com/graphql',
            json={
                'query': '''
                query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
                    problemsetQuestionList: questionList(
                        categorySlug: $categorySlug
                        limit: $limit
                        skip: $skip
                        filters: $filters
                    ) {
                        total: totalNum
                        questions: data {
                            questionId
                            title
                            titleSlug
                            difficulty
                            acRate
                            status
                            stats
                            isPaidOnly
                        }
                    }
                }
                ''',
                'variables': variables
            }
        )

        # Check if user is authenticated
        user_id = None
        if current_user.is_authenticated:
            user_id = current_user.id

        data = response.json()
        if 'errors' in data:
            return jsonify({'status': 'error', 'message': 'Error fetching data from LeetCode API'}), 500

        questions_data = data['data']['problemsetQuestionList']
        total_questions = questions_data['total']
        questions = questions_data['questions']

        # Get solved problems for the current user if authenticated
        solved_problems = set()
        if user_id:
            solved_problems = {sp.problem_id for sp in SolvedProblem.query.filter_by(user_id=user_id, solved=True).all()}

        # Process each problem
        processed_problems = []
        for q in questions:
            if not q['isPaidOnly']:
                stats = json.loads(q['stats'])
                processed_problem = {
                    'id': q['questionId'],
                    'title': q['title'],
                    'difficulty': q['difficulty'],
                    'acceptance_rate': round(float(q['acRate']), 1),
                    'total_accepted': int(stats['totalAcceptedRaw']),
                    'total_submissions': int(stats['totalSubmissionRaw']),
                    'solved': q['questionId'] in solved_problems if user_id else False
                }
                processed_problems.append(processed_problem)

        # Calculate total pages
        total_pages = math.ceil(total_questions / per_page)

        return jsonify({
            'status': 'success',
            'problems': processed_problems,
            'total_pages': total_pages,
            'current_page': page
        })

    except Exception as e:
        app.logger.error(f"Error in scrape_leetcode: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api')
@login_required
def api_docs():
    try:
        return render_template('api-docs.html')
    except Exception as e:
        print(f"Error rendering api-docs template: {str(e)}")
        return str(e), 500

@app.route('/api/swagger.json')
@login_required_json
def swagger_json():
    try:
        return send_from_directory(os.path.join(BASE_DIR, 'static', 'api-docs'), 'swagger.json')
    except Exception as e:
        print(f"Error serving swagger.json: {str(e)}")
        return str(e), 500

@app.route('/user-stats', methods=['GET', 'POST'])
@login_required
def user_stats():
    if request.method == 'POST':
        username = request.form.get('username')
        if not username:
            return jsonify({'status': 'error', 'message': 'Username is required'})

        try:
            # Get user stats first
            user_query = """
            query getUserProfile($username: String!) {
              matchedUser(username: $username) {
                profile {
                  ranking
                  reputation
                  starRating
                }
                submitStats: submitStatsGlobal {
                  acSubmissionNum {
                    difficulty
                    count
                    submissions
                  }
                }
              }
            }
            """
            
            user_variables = {"username": username}
            
            user_response = requests.post(
                'https://leetcode.com/graphql',
                json={'query': user_query, 'variables': user_variables},
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
            )
            
            user_data = user_response.json()
            print(f"User API Response: {user_data}")  # Debug log
            
            if 'errors' in user_data:
                error_message = user_data['errors'][0]['message'] if user_data['errors'] else 'Unknown error'
                print(f"GraphQL Error: {error_message}")  # Debug log
                return jsonify({
                    'status': 'error',
                    'message': f'Error fetching user data: {error_message}'
                })
            
            if not user_data.get('data'):
                print("No data in response")  # Debug log
                return jsonify({
                    'status': 'error',
                    'message': 'Invalid response from LeetCode API'
                })
            
            if not user_data['data'].get('matchedUser'):
                print("User not found")  # Debug log
                return jsonify({
                    'status': 'error',
                    'message': 'User not found'
                })

            # Get problem counts using the optimized query
            problems_query = """
            query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
              all: questionList(categorySlug: $categorySlug, limit: $limit, skip: $skip, filters: $filters) {
                totalNum
              }
              easy: questionList(categorySlug: $categorySlug, filters: {difficulty: EASY}) {
                totalNum
              }
              medium: questionList(categorySlug: $categorySlug, filters: {difficulty: MEDIUM}) {
                totalNum
              }
              hard: questionList(categorySlug: $categorySlug, filters: {difficulty: HARD}) {
                totalNum
              }
            }
            """
            
            problems_variables = {
                "categorySlug": "",
                "skip": 0,
                "limit": 1,  # We only need the count
                "filters": {}
            }

            problems_response = requests.post(
                'https://leetcode.com/graphql',
                json={'query': problems_query, 'variables': problems_variables},
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
            )
            
            problems_data = problems_response.json()
            print(f"Problems API Response: {problems_data}")  # Debug log
            
            if 'errors' in problems_data:
                error_message = problems_data['errors'][0]['message'] if problems_data['errors'] else 'Unknown error'
                print(f"GraphQL Error: {error_message}")  # Debug log
                return jsonify({
                    'status': 'error',
                    'message': f'Error fetching problem data: {error_message}'
                })
            
            if not problems_data.get('data'):
                print("No data in problems response")  # Debug log
                return jsonify({
                    'status': 'error',
                    'message': 'Invalid response from LeetCode API for problems'
                })
            
            result_data = problems_data['data']
            
            # Map the difficulty levels from LeetCode's API response (EASY, MEDIUM, HARD)
            # to our frontend format (Easy, Medium, Hard)
            difficulty_totals = {
                'Easy': result_data['easy']['totalNum'],
                'Medium': result_data['medium']['totalNum'],
                'Hard': result_data['hard']['totalNum']
            }
            
            # Combine the data
            result = {
                'status': 'success',
                'data': {
                    'profile': user_data['data']['matchedUser']['profile'],
                    'submitStats': {
                        'acSubmissionNum': []
                    },
                    'totalProblems': {
                        'total': result_data['all']['totalNum'],
                        'byDifficulty': difficulty_totals
                    }
                }
            }
            
            # Map user's submission stats from EASY/MEDIUM/HARD to Easy/Medium/Hard
            difficulty_map = {
                'EASY': 'Easy',
                'MEDIUM': 'Medium',
                'HARD': 'Hard',
                'All': 'All'
            }
            
            for stat in user_data['data']['matchedUser']['submitStats']['acSubmissionNum']:
                mapped_difficulty = difficulty_map.get(stat['difficulty'], stat['difficulty'])
                result['data']['submitStats']['acSubmissionNum'].append({
                    'difficulty': mapped_difficulty,
                    'count': stat['count']
                })
            
            return jsonify(result)
            
        except Exception as e:
            print(f"Error: {str(e)}")  # Debug log
            import traceback
            print(f"Traceback: {traceback.format_exc()}")  # Full traceback for debugging
            return jsonify({
                'status': 'error',
                'message': 'An error occurred while fetching user statistics'
            })
    
    return render_template('user_stats.html')

@app.route('/problem-counts')
def problem_counts():
    try:
        # Query to get total count and counts by difficulty
        problems_query = """
        query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
          all: questionList(categorySlug: $categorySlug, limit: $limit, skip: $skip, filters: $filters) {
            totalNum
          }
          easy: questionList(categorySlug: $categorySlug, filters: {difficulty: EASY}) {
            totalNum
          }
          medium: questionList(categorySlug: $categorySlug, filters: {difficulty: MEDIUM}) {
            totalNum
          }
          hard: questionList(categorySlug: $categorySlug, filters: {difficulty: HARD}) {
            totalNum
          }
        }
        """
        
        variables = {
            "categorySlug": "",
            "skip": 0,
            "limit": 1,  # We only need the count, so limit to 1
            "filters": {}
        }

        response = requests.post(
            'https://leetcode.com/graphql',
            json={'query': problems_query, 'variables': variables},
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        )
        
        if not response.ok:
            return jsonify({
                'status': 'error',
                'message': f'HTTP Error: {response.status_code}'
            })

        data = response.json()
        
        if 'errors' in data:
            return jsonify({
                'status': 'error',
                'message': 'Error fetching problem data'
            })
        
        result_data = data['data']
        
        return jsonify({
            'status': 'success',
            'data': {
                'total': result_data['all']['totalNum'],
                'byDifficulty': {
                    'Easy': result_data['easy']['totalNum'],
                    'Medium': result_data['medium']['totalNum'],
                    'Hard': result_data['hard']['totalNum']
                }
            }
        })
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'An error occurred while fetching problem counts'
        })

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True) 