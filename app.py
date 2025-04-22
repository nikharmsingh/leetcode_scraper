from flask import Flask, render_template, jsonify, redirect, url_for, request
import requests
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv
import time
import json

app = Flask(__name__)
load_dotenv()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/problems')
def problems():
    return render_template('problems.html')

@app.route('/scrape-leetcode')
def scrape_leetcode():
    try:
        # Get pagination parameters from request
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
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
        
        variables = {
            "categorySlug": "",
            "limit": per_page,
            "skip": offset,
            "filters": {
                "orderBy": "FRONTEND_ID",
                "sortOrder": "ASCENDING",
                "difficulty": None,
                "status": None,
                "tags": []
            }
        }
        
        response = requests.post(
            url,
            headers=headers,
            json={
                'query': query,
                'variables': variables
            }
        )
        
        data = response.json()
        
        if 'errors' in data:
            raise Exception(data['errors'][0]['message'])
            
        questions = data['data']['problemsetQuestionList']['questions']
        total = data['data']['problemsetQuestionList']['total']
        
        problems = []
        for q in questions:
            problems.append({
                'id': q['questionId'],
                'title': q['title'],
                'difficulty': q['difficulty'],
                'acceptance_rate': round(float(q['acRate']), 1),
                'url': f"https://leetcode.com/problems/{q['titleSlug']}/"
            })
        
        total_pages = (total + per_page - 1) // per_page  # Ceiling division
        
        return jsonify({
            'status': 'success',
            'problems': problems,
            'total': total,
            'current_page': page,
            'total_pages': total_pages,
            'per_page': per_page
        })
    except Exception as e:
        print(f"Error: {str(e)}")  # Add logging for debugging
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=True) 