from flask import Flask, render_template, jsonify, redirect, url_for, request, send_from_directory, session
import requests
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv
import time
import json
import re
from urllib.parse import urlencode

# Get the absolute path to the current directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'),
            static_url_path='')
app.secret_key = os.urandom(24)  # Required for session management
load_dotenv()

def authenticate_request(session_obj, url):
    """Add authentication headers to the request"""
    leetcode_session = session_obj.cookies.get('LEETCODE_SESSION')
    csrf_token = session_obj.cookies.get('csrftoken')
    
    # Fall back to environment variables if not in session
    if not leetcode_session or not csrf_token:
        leetcode_session = os.getenv('LEETCODE_SESSION')
        csrf_token = os.getenv('LEETCODE_CSRF_TOKEN')
    
    if not leetcode_session or not csrf_token:
        return None
    
    headers = {
        'Cookie': f'LEETCODE_SESSION={leetcode_session}; csrftoken={csrf_token}',
        'x-csrftoken': csrf_token,
        'Referer': url,
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://leetcode.com'
    }
    return headers

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/problems')
def problems():
    # Check if user is logged in
    username = session.get('leetcode_username')
    if username:
        # Update the UI to show logged in state
        return render_template('problems.html', logged_in=True, username=username)
    return render_template('problems.html', logged_in=False)

@app.route('/api')
def api_docs():
    try:
        return render_template('api-docs.html')
    except Exception as e:
        print(f"Error rendering api-docs template: {str(e)}")
        return str(e), 500

@app.route('/api/swagger.json')
def swagger_json():
    try:
        return send_from_directory(os.path.join(BASE_DIR, 'static', 'api-docs'), 'swagger.json')
    except Exception as e:
        print(f"Error serving swagger.json: {str(e)}")
        return str(e), 500

@app.route('/login')
def login():
    try:
        # Initialize session
        leetcode_session = requests.Session()
        
        # Get CSRF token
        url = "https://leetcode.com/graphql"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'https://leetcode.com',
            'Referer': 'https://leetcode.com/'
        }
        
        # First query to get CSRF token
        query = """
        query globalData {
          userStatus {
            isSignedIn
            username
          }
        }
        """
        
        response = leetcode_session.post(url, json={'query': query}, headers=headers)
        
        if not response.ok:
            return jsonify({'status': 'error', 'message': 'Failed to access LeetCode API'}), 400
        
        # Get CSRF token from cookies
        csrf_token = leetcode_session.cookies.get('csrftoken')
        if not csrf_token:
            return jsonify({'status': 'error', 'message': 'Could not get CSRF token'}), 400
        
        # Store the session and CSRF token
        session['leetcode_session'] = leetcode_session.cookies.get_dict()
        session['csrf_token'] = csrf_token
        
        return jsonify({
            'status': 'success',
            'csrf_token': csrf_token
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/verify-login', methods=['POST'])
def verify_login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'status': 'error', 'message': 'Username and password are required'}), 400
        
        # Create a session
        leetcode_session = requests.Session()
        
        # Get CSRF token first
        url = "https://leetcode.com/graphql"
        headers = authenticate_request(leetcode_session, url)
        if not headers:
            return jsonify({'status': 'error', 'message': 'Authentication headers not found'}), 400
        
        # Try to login
        login_query = """
        mutation login($username: String!, $password: String!) {
          login(username: $username, password: $password) {
            ok
            error
          }
        }
        """
        
        response = leetcode_session.post(
            url,
            json={
                'query': login_query,
                'variables': {
                    'username': username,
                    'password': password
                }
            },
            headers=headers
        )
        
        if not response.ok:
            return jsonify({'status': 'error', 'message': 'Login request failed'}), 400
        
        data = response.json()
        if 'errors' in data:
            return jsonify({'status': 'error', 'message': data['errors'][0]['message']}), 400
        
        login_result = data.get('data', {}).get('login', {})
        if not login_result.get('ok'):
            return jsonify({'status': 'error', 'message': login_result.get('error', 'Login failed')}), 400
        
        # Verify login by getting user info
        user_query = """
        query globalData {
          userStatus {
            isSignedIn
            username
          }
        }
        """
        
        response = leetcode_session.post(
            url,
            json={'query': user_query},
            headers=headers
        )
        
        if not response.ok:
            return jsonify({'status': 'error', 'message': 'Failed to verify login'}), 400
        
        data = response.json()
        if not data.get('data', {}).get('userStatus', {}).get('isSignedIn'):
            return jsonify({'status': 'error', 'message': 'Login verification failed'}), 400
        
        username = data['data']['userStatus']['username']
        
        # Store session in app config
        app.config['leetcode_session'] = leetcode_session
        app.config['leetcode_username'] = username
        
        # Set session cookie for the user
        session['leetcode_username'] = username
        session['leetcode_session'] = leetcode_session.cookies.get_dict()
        session['csrf_token'] = leetcode_session.cookies.get('csrftoken')
        
        return jsonify({
            'status': 'success',
            'message': 'Login successful',
            'username': username
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/logout', methods=['POST'])
def logout():
    try:
        app.config.pop('leetcode_session', None)
        app.config.pop('leetcode_username', None)
        session.pop('leetcode_username', None)
        return jsonify({'status': 'success', 'message': 'Logout successful'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/scrape-leetcode')
def scrape_leetcode():
    try:
        # Get pagination parameters from request
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        search_query = request.args.get('search', '').strip()
        difficulty = request.args.get('difficulty', '').strip()
        username = request.args.get('username', '').strip()  # Get username from request
        offset = (page - 1) * per_page

        # Using LeetCode's GraphQL API
        url = "https://leetcode.com/graphql"
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # GraphQL query to get problem list
        query = """
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
                }
            }
        }
        """

        filters = {
            "orderBy": "FRONTEND_ID",
            "sortOrder": "ASCENDING",
            "status": None,
            "tags": []
        }

        if search_query:
            filters["searchKeywords"] = search_query

        if difficulty and difficulty.lower() != 'all':
            filters["difficulty"] = difficulty.upper()
        
        variables = {
            "categorySlug": "",
            "limit": per_page,
            "skip": offset,
            "filters": filters
        }
        
        response = requests.post(
            url,
            headers=headers,
            json={
                'query': query,
                'variables': variables
            }
        )
        
        if not response.ok:
            return jsonify({
                'status': 'error',
                'message': f'HTTP Error: {response.status_code}'
            }), 500

        data = response.json()
        
        if 'errors' in data:
            return jsonify({
                'status': 'error',
                'message': 'Error fetching problems'
            }), 400
            
        questions = data['data']['problemsetQuestionList']['questions']
        total = data['data']['problemsetQuestionList']['total']
        
        # Get solved problems if username is provided
        solved_problems = set()
        if username:
            try:
                # Get user's solved problems
                solved_query = """
                query userProblemsSolved($username: String!) {
                    matchedUser(username: $username) {
                        submitStatsGlobal {
                            acSubmissionNum {
                                difficulty
                                count
                                submissions
                            }
                        }
                    }
                }
                """
                
                solved_response = requests.post(
                    url,
                    headers=headers,
                    json={
                        'query': solved_query,
                        'variables': {'username': username}
                    }
                )
                
                if solved_response.ok:
                    solved_data = solved_response.json()
                    if 'data' in solved_data and 'matchedUser' in solved_data['data']:
                        for stat in solved_data['data']['matchedUser']['submitStatsGlobal']['acSubmissionNum']:
                            if stat['count'] > 0:
                                solved_problems.add(stat['difficulty'].lower())
            except Exception as e:
                print(f"Error fetching solved problems: {str(e)}")
        
        problems = []
        for q in questions:
            problems.append({
                'id': q['questionId'],
                'title': q['title'],
                'difficulty': q['difficulty'],
                'acceptance_rate': round(float(q['acRate']), 1),
                'url': f"https://leetcode.com/problems/{q['titleSlug']}/",
                'solved': q['difficulty'].lower() in solved_problems
            })
        
        total_pages = (total + per_page - 1) // per_page
        
        return jsonify({
            'status': 'success',
            'problems': problems,
            'total': total,
            'current_page': page,
            'total_pages': total_pages,
            'per_page': per_page
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/user-stats', methods=['GET', 'POST'])
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
    app.run(debug=True) 