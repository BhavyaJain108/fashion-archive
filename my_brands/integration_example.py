#!/usr/bin/env python3
"""
My Brands Integration Example
============================

This file shows exactly what to add to your existing clean_api.py file
to integrate the My Brands functionality.

INTEGRATION INSTRUCTIONS:
1. Add the imports at the top of your clean_api.py file  
2. Add the registration call before app.run()
3. That's it! All My Brands endpoints will be available.
"""

# ===== ADD THESE IMPORTS TO THE TOP OF clean_api.py =====

try:
    from my_brands.brands_api import register_brands_endpoints
    MY_BRANDS_AVAILABLE = True
    print("✅ My Brands feature available")
except ImportError as e:
    MY_BRANDS_AVAILABLE = False
    print(f"⚠️  My Brands feature not available: {e}")


# ===== ADD THIS BEFORE app.run() IN clean_api.py =====

def setup_my_brands_integration(app):
    """Add My Brands endpoints to the existing Flask app"""
    if MY_BRANDS_AVAILABLE:
        try:
            register_brands_endpoints(app)
            print("🎭 My Brands API endpoints registered")
            print("📱 Available at /api/brands, /api/products, etc.")
        except Exception as e:
            print(f"❌ Error registering My Brands endpoints: {e}")
    else:
        print("⚠️  My Brands integration skipped - dependencies missing")


# ===== EXAMPLE OF COMPLETE INTEGRATION =====

if __name__ == '__main__':
    """
    Example of how your clean_api.py should look after integration:
    
    # Your existing imports...
    from flask import Flask, jsonify, request, send_file
    from flask_cors import CORS
    # ... other imports ...
    
    # ADD THIS IMPORT
    try:
        from my_brands.brands_api import register_brands_endpoints
        MY_BRANDS_AVAILABLE = True
    except ImportError:
        MY_BRANDS_AVAILABLE = False
    
    app = Flask(__name__)
    CORS(app, methods=['GET', 'POST', 'DELETE', 'OPTIONS'])
    
    # All your existing endpoints...
    @app.route('/api/seasons', methods=['POST'])
    def get_seasons():
        # existing code...
    
    # ... all other existing endpoints ...
    
    # ADD THIS BEFORE app.run()
    if MY_BRANDS_AVAILABLE:
        register_brands_endpoints(app)
        print("🎭 My Brands feature integrated successfully")
    
    print("🎭 Clean API Backend - Enhanced with My Brands")
    app.run(host='127.0.0.1', port=8081, debug=True, threaded=True)
    """
    
    # For testing - create a minimal Flask app with My Brands
    from flask import Flask
    from flask_cors import CORS
    
    app = Flask(__name__)
    CORS(app, methods=['GET', 'POST', 'DELETE', 'OPTIONS'])
    
    @app.route('/')
    def home():
        return {
            'message': 'Fashion Archive API with My Brands',
            'features': [
                'Brand validation with AI',
                'Smart product scraping',
                'Pattern-based detection',
                'Favorites management'
            ]
        }
    
    # Integrate My Brands
    setup_my_brands_integration(app)
    
    print("🚀 Test server with My Brands integration")
    print("🔗 Visit http://localhost:8081 to test")
    print("📋 Available endpoints:")
    print("   - POST /api/brands (add brand)")
    print("   - GET /api/brands (list brands)")
    print("   - POST /api/brands/analyze (analyze URL)")
    print("   - GET /api/brands/stats (statistics)")
    
    app.run(host='127.0.0.1', port=8081, debug=True, threaded=True)