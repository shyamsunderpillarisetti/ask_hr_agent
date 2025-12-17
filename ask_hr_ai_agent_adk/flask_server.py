from flask import Flask, request, jsonify, render_template
from typing import Dict, Any, Tuple
import traceback
import os
from agent import chat_with_workday, reset_auth_cache

app = Flask(__name__)

if os.getenv("ASKHR_RESET_AUTH_ON_STARTUP", "true").lower() in ("1", "true", "yes"):
    reset_auth_cache()

@app.route('/')
def index() -> str:
    """Serve the main HTML interface."""
    return render_template('index.html')


@app.route('/chat', methods=['POST'])
def chat() -> Tuple[Dict[str, Any], int]:
    """Handle chat messages."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON body provided'}), 400
        
        message = data.get('message', '').strip()
        
        if not message:
            return jsonify({'error': 'No message provided'}), 400
        
        response = chat_with_workday(message)
        return jsonify({'response': response}), 200
        
    except ValueError as e:
        return jsonify({'error': f'Validation error: {str(e)}'}), 400
    except TimeoutError as e:
        return jsonify({'error': f'Request timeout: {str(e)}'}), 504
    except Exception as e:
        print(f"Unexpected error: {traceback.format_exc()}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.errorhandler(404)
def not_found(error) -> Tuple[Dict[str, str], int]:
    """Handle 404 errors."""
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(error) -> Tuple[Dict[str, str], int]:
    """Handle 500 errors."""
    return jsonify({'error': 'Internal server error'}), 500

@app.route('/reset', methods=['POST'])
def reset() -> Tuple[Dict[str, Any], int]:
    """Clear cached auth so next request prompts login again."""
    try:
        from agent import reset_auth_cache
        ok = reset_auth_cache()
        return jsonify({'success': ok, 'message': 'Auth cache cleared. Next request will trigger login.'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # Disable Flask's auto-reloader to keep the dev server stable in VS Code terminals
    app.run(debug=True, host='127.0.0.1', port=5000, use_reloader=False)
