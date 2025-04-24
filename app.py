from flask import Flask, render_template, jsonify, redirect, url_for, request, send_from_directory, session, flash
import requests
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv
import time
import json
import re
from urllib.parse import urlencode
from models import User, SolvedProblem
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from functools import wraps
import math
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from bson.objectid import ObjectId
from datetime import datetime
import certifi

# Get the absolute path to the current directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'),
            static_url_path='')

# Load environment variables
load_dotenv()

# Configure MongoDB
uri = os.getenv('MONGODB_URI')
client = MongoClient(
    uri,
    server_api=ServerApi('1'),
    tls=True,
    tlsCAFile=certifi.where()
)
db = client.leetcode_scraper

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['API_KEY'] = os.getenv('API_KEY')

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Make API key available in all templates
@app.context_processor
def inject_api_key():
    return {'api_key': app.config['API_KEY']}

@login_manager.user_loader
def load_user(user_id):
    try:
        user_data = db.users.find_one({'_id': ObjectId(user_id)})
        if user_data:
            return User.from_dict(user_data)
    except Exception:
        # If there's any error (invalid ObjectId, etc.), return None
        return None
    return None

def login_required_json(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'status': 'error', 'message': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('x-api-key')
        if not api_key or api_key != app.config['API_KEY']:
            return jsonify({'status': 'error', 'message': 'Invalid API key'}), 401
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
        
        if db.users.find_one({'username': username}):
            flash('Username already exists')
            return redirect(url_for('register'))
            
        if db.users.find_one({'email': email}):
            flash('Email already exists')
            return redirect(url_for('register'))
            
        user = User(username=username, email=email, password=password)
        user_dict = user.to_dict()
        result = db.users.insert_one(user_dict)
        user._id = result.inserted_id
        
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
        user_data = db.users.find_one({'username': username})
        
        if user_data:
            user = User.from_dict(user_data)
            if user.check_password(password):
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
        solved_problem = db.solved_problems.find_one({
            'user_id': str(current_user._id),
            'problem_id': problem_id
        })
        
        if solved_problem:
            db.solved_problems.update_one(
                {'_id': solved_problem['_id']},
                {'$set': {'solved': solved, 'updated_at': datetime.utcnow()}}
            )
        else:
            problem = SolvedProblem(
                user_id=str(current_user._id),
                problem_id=problem_id,
                solved=solved
            )
            db.solved_problems.insert_one(problem.to_dict())
            
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/scrape-leetcode')
@require_api_key
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
            user_id = str(current_user._id)

        data = response.json()
        if 'errors' in data:
            return jsonify({'status': 'error', 'message': 'Error fetching data from LeetCode API'}), 500

        questions_data = data['data']['problemsetQuestionList']
        total_questions = questions_data['total']
        questions = questions_data['questions']

        # Get solved problems for the current user if authenticated
        solved_problems = set()
        if user_id:
            solved_problems = {sp['problem_id'] for sp in db.solved_problems.find({'user_id': user_id, 'solved': True})}

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
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api')
@login_required
def api_docs():
    return render_template('api-docs.html')

@app.route('/api/swagger.json')
@login_required_json
def swagger_json():
    return send_from_directory(os.path.join(BASE_DIR, 'static', 'api-docs'), 'swagger.json')

@app.route('/user-stats', methods=['GET', 'POST'])
@require_api_key
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
            
            if 'errors' in user_data:
                error_message = user_data['errors'][0]['message'] if user_data['errors'] else 'Unknown error'
                return jsonify({
                    'status': 'error',
                    'message': f'Error fetching user data: {error_message}'
                })
            
            if not user_data.get('data'):
                return jsonify({
                    'status': 'error',
                    'message': 'Invalid response from LeetCode API'
                })
            
            if not user_data['data'].get('matchedUser'):
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
            
            if 'errors' in problems_data:
                error_message = problems_data['errors'][0]['message'] if problems_data['errors'] else 'Unknown error'
                return jsonify({
                    'status': 'error',
                    'message': f'Error fetching problem data: {error_message}'
                })
            
            if not problems_data.get('data'):
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
            return jsonify({
                'status': 'error',
                'message': 'An error occurred while fetching user statistics'
            })
    
    return render_template('user_stats.html')

@app.route('/problem-counts')
@require_api_key
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
        return jsonify({
            'status': 'error',
            'message': 'An error occurred while fetching problem counts'
        })

@app.route('/health')
def health():
    try:
        # Check MongoDB connection
        client.admin.command('ping')
        mongodb_status = 'healthy'
    except Exception as e:
        mongodb_status = 'unhealthy'
        mongodb_error = str(e)

    # Check if API key is configured
    api_key_status = 'configured' if app.config['API_KEY'] else 'not configured'

    return jsonify({
        'status': 'healthy',
        'message': 'Service is running',
        'components': {
            'mongodb': {
                'status': mongodb_status,
                'error': mongodb_error if mongodb_status == 'unhealthy' else None
            },
            'api_key': {
                'status': api_key_status
            }
        }
    }), 200 if mongodb_status == 'healthy' else 503

if __name__ == '__main__':
    with app.app_context():
        db.users.create_index('username', unique=True)
        db.users.create_index('email', unique=True)
    app.run(debug=True) 