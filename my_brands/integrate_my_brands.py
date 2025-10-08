#!/usr/bin/env python3
"""
My Brands Integration Patch
===========================

Run this to integrate My Brands with your existing clean_api.py
This will add the necessary imports and registration without modifying your existing file.
"""

import os
import sys

def integrate_my_brands():
    """Add My Brands integration to clean_api.py"""
    
    api_file = "clean_api.py"
    
    if not os.path.exists(api_file):
        print("❌ clean_api.py not found in current directory")
        return False
    
    # Read current content
    with open(api_file, 'r') as f:
        content = f.read()
    
    # Check if already integrated
    if 'register_brands_endpoints' in content:
        print("✅ My Brands already integrated in clean_api.py")
        return True
    
    print("🔧 Integrating My Brands with clean_api.py...")
    
    # Add import after other imports
    if 'from favourites_db import favourites_db' in content:
        content = content.replace(
            'from favourites_db import favourites_db',
            '''from favourites_db import favourites_db

# My Brands integration
try:
    from my_brands.brands_api import register_brands_endpoints
    MY_BRANDS_AVAILABLE = True
    print("✅ My Brands feature available")
except ImportError as e:
    MY_BRANDS_AVAILABLE = False
    print(f"⚠️  My Brands feature not available: {e}")'''
        )
    else:
        print("❌ Could not find import location in clean_api.py")
        return False
    
    # Add registration before app.run()
    if "app.run(host='127.0.0.1', port=8081" in content:
        content = content.replace(
            "app.run(host='127.0.0.1', port=8081",
            '''# Register My Brands endpoints
if MY_BRANDS_AVAILABLE:
    register_brands_endpoints(app)
    print("🎭 My Brands API endpoints registered")

app.run(host='127.0.0.1', port=8081'''
        )
    else:
        print("❌ Could not find app.run() location in clean_api.py")
        return False
    
    # Write back the modified content
    with open(api_file, 'w') as f:
        f.write(content)
    
    print("✅ My Brands successfully integrated with clean_api.py")
    print("\n📋 Integration completed:")
    print("   - Added My Brands import")
    print("   - Added endpoint registration")
    print("   - Backend ready for My Brands UI")
    print("\n🚀 Restart your server: python clean_api.py")
    
    return True

if __name__ == "__main__":
    print("🎭 MY BRANDS INTEGRATION")
    print("=" * 40)
    
    if integrate_my_brands():
        print("\n✅ Integration successful!")
        print("\nNext steps:")
        print("1. Restart your backend: python clean_api.py")
        print("2. Start your frontend: cd web_ui && npm start")
        print("3. Navigate to Pages → My Brands")
        print("4. Add Jukuhara or other fashion brands!")
    else:
        print("\n❌ Integration failed!")
        print("Check the error messages above and try again.")