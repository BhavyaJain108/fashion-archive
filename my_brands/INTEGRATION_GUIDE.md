# My Brands Integration Guide

## Overview

This guide shows how to integrate the My Brands feature with your existing Fashion Archive system.

## Integration Steps

### 1. Add My Brands API to Existing Server

Add these lines to your `clean_api.py` file to integrate the My Brands endpoints:

```python
# Add this import at the top after your existing imports
from my_brands.brands_api import register_brands_endpoints

# Add this line before app.run() at the bottom of the file  
register_brands_endpoints(app)
```

### 2. Environment Setup

Create a `.env` file in your project root with:

```bash
# LLM Configuration (choose one)
LLM_PROVIDER=claude  # or 'openai' 
CLAUDE_API_KEY=your_claude_api_key_here
# OPENAI_API_KEY=your_openai_api_key_here  # if using OpenAI

# My Brands Database
BRANDS_DB_PATH=my_brands/brands.db
```

### 3. Install Dependencies

```bash
pip install anthropic  # for Claude
# pip install openai  # for OpenAI
pip install beautifulsoup4 requests python-dotenv
```

### 4. Database Initialization

The brands database will be created automatically when first used. The database file will be stored at `my_brands/brands.db`.

### 5. UI Integration 

The My Brands UI panel is already integrated! Just make sure:

1. Your React app is running (`npm start` in the `web_ui` directory)
2. The backend server is running (`python clean_api.py`)
3. Navigate to the "My Brands" section in the menu

## API Endpoints Added

### Brand Management
- `POST /api/brands` - Add new brand (with AI validation)
- `GET /api/brands` - List all brands  
- `GET /api/brands/{id}` - Get brand details
- `GET /api/brands/stats` - Get collection statistics

### Product Scraping
- `POST /api/brands/{id}/scrape` - Scrape products for a brand
- `GET /api/brands/{id}/products` - Get products for a brand

### Analysis & Validation  
- `POST /api/brands/analyze` - Analyze brand URL (preview before adding)

### Favorites
- `POST /api/products/{id}/favorite` - Add product to favorites
- `GET /api/brand-favorites` - Get all favorite products

## How It Works

### 1. Brand Addition Workflow
```
User enters URL → Domain validation → Website analysis → AI brand validation → Scraping strategy detection → Database storage
```

### 2. AI Validation Process
- **Domain Check**: Blocks major retailers (Amazon, Zara, etc.)
- **Content Analysis**: AI analyzes website content to determine if it's a small independent brand
- **Scraping Assessment**: AI determines best scraping strategy based on site structure

### 3. Smart Product Detection
The system uses three complementary methods:
- **Pattern Analysis**: Analyzes image filename patterns (e.g., "product-001.jpg", "product-002.jpg")  
- **Structure Analysis**: Finds most common repeated HTML structures
- **Logical Reasoning**: Looks for elements that logically represent products (image + title + price + link)

### 4. Scraping Strategies
Six different strategies for different website types:
1. **homepage-all-products**: All products on main page
2. **category-based**: Navigate categories → products  
3. **product-grid**: Grid layouts with multiple products
4. **paginated**: Handle multiple pages/pagination
5. **image-click**: Click images for full resolution  
6. **single-page-scroll**: Infinite scroll or long pages

## Testing the Integration

### 1. Start the Backend
```bash
python clean_api.py
```

### 2. Start the Frontend  
```bash
cd web_ui
npm start
```

### 3. Test Brand Addition
1. Open the app in browser (usually http://localhost:3000)
2. Navigate to "My Brands" 
3. Click "Add Brand"
4. Enter a small fashion brand URL (e.g., a boutique designer's website)
5. Wait for validation and scraping analysis

### 4. Test Product Scraping
Once a brand is added and approved:
1. Select the brand from the list
2. The system will show scraping strategy and estimated products
3. Products will be scraped and displayed (this feature is ready in the backend)

## Example Brand URLs for Testing

These are examples of the types of brands the system should approve:

- Independent designer websites
- Small boutique fashion brands  
- Emerging fashion labels
- Direct-to-consumer fashion startups

Avoid testing with:
- Amazon, eBay, major marketplaces
- Department stores (Nordstrom, Macy's)
- Fast fashion chains (H&M, Zara, Uniqlo)

## Configuration Options

### LLM Provider Selection
You can switch between AI providers in the `.env` file:
- `claude`: Uses Anthropic's Claude (recommended)
- `openai`: Uses OpenAI GPT-4

### Scraping Behavior
- **Rate Limiting**: 2-second delays between requests  
- **Concurrent Brands**: Maximum 3 brands scraped simultaneously
- **Request Timeout**: 15 seconds per request
- **Duplicate Detection**: Products deduplicated by URL and title

## Troubleshooting

### Common Issues

**"Brand validation failed"**
- The AI determined this isn't a small independent fashion brand
- Try with a smaller, more boutique-style brand website

**"Website not accessible"**  
- The website might be down or blocking requests
- Try a different URL or wait and try again

**"No scraping strategy found"**
- The website structure couldn't be analyzed  
- The site might use heavy JavaScript or anti-scraping measures

**API connection errors**
- Make sure the backend server is running on port 8081
- Check that the my_brands endpoints are properly registered

### Debug Mode
Add `debug=True` to see detailed logging:
```python
app.run(host='127.0.0.1', port=8081, debug=True, threaded=True)
```

## Architecture Overview

```
Frontend (React)
    ↓ API calls
Backend (Flask)
    ├── Existing Fashion Archive endpoints
    └── My Brands endpoints
        ├── LLM Client (AI validation)
        ├── Scraping Detector (strategy analysis)
        ├── Product Scraper (data extraction)  
        └── Brands Database (SQLite)
```

## Security Considerations

- API keys are stored in environment variables
- Website requests use standard browser headers
- Rate limiting prevents server overload  
- No sensitive data is stored in the database

## Performance Notes

- Brand validation: ~3-5 seconds (one-time per brand)
- Product scraping: ~5-15 seconds depending on site size
- Database operations: Near-instantaneous  
- UI updates: Real-time via API calls

## Next Steps

Once integrated and tested, you can:
1. Add more sophisticated scraping strategies for complex sites
2. Implement product image downloading and storage
3. Add product change detection and alerts
4. Create product comparison and wishlist features
5. Add export functionality for product catalogs