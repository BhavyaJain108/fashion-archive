# Premium Scraper API Integration

## Overview

The premium scraper has been successfully integrated with the existing Flask API (`clean_api.py`). This provides a robust backend for scraping any fashion brand website using intelligent pattern detection and LLM analysis.

## API Endpoints

All premium scraper endpoints are available under `/api/premium/`:

### 1. Test Connection
```
GET /api/premium/test
```
Verifies the premium scraper API is running and lists available endpoints.

### 2. Analyze Brand
```
POST /api/premium/analyze
Content-Type: application/json

{
  "brand_url": "https://example-brand.com"
}
```
Analyzes a brand website to determine if it can be scraped and estimates the number of product categories.

**Response:**
```json
{
  "success": true,
  "is_scrapable": true,
  "analysis": {
    "category_pages_found": 5,
    "categories": ["Accessories", "Clothing", "Shoes"],
    "confidence": "high",
    "estimated_time": 25
  },
  "message": "Found 5 product category pages"
}
```

### 3. Start Scraping Job
```
POST /api/premium/scrape
Content-Type: application/json

{
  "brand_url": "https://example-brand.com",
  "brand_name": "Example Brand" (optional)
}
```
Starts a background scraping job for the specified brand.

**Response:**
```json
{
  "success": true,
  "message": "Scraping job started successfully",
  "job_id": "scrape_1234567890",
  "job": {
    "status": "running",
    "brand_name": "Example Brand",
    "progress": 0,
    "current_action": "Analyzing brand navigation..."
  }
}
```

### 4. Check Job Status
```
GET /api/premium/scrape/<job_id>
```
Gets the current status of a scraping job.

**Response:**
```json
{
  "success": true,
  "job": {
    "job_id": "scrape_1234567890",
    "status": "completed",
    "brand_name": "Example Brand",
    "progress": 100,
    "total_products": 43,
    "categories_processed": 6,
    "total_categories": 6,
    "current_action": "Completed! Scraped 43 products from 6 categories",
    "elapsed_time": 37.5,
    "start_time": "2025-10-03T09:06:00.217688",
    "end_time": "2025-10-03T09:06:37.715319"
  }
}
```

### 5. Get Scraped Products
```
GET /api/premium/scrape/<job_id>/products?page=1&per_page=50
```
Retrieves the products from a completed scraping job with pagination.

**Response:**
```json
{
  "success": true,
  "products": [
    {
      "product_name": "JP SOUNDS REVERSIBLE BEANIE V2",
      "product_url": "https://jukuhara.jp/products/v2-jp-sounds-reversible-beanie",
      "image_url": "https://jukuhara.jp/cdn/shop/files/beanie5.png",
      "price": "",
      "availability": "Unknown",
      "brand": "Jukuhara",
      "category_name": "Accessories",
      "category_url": "https://jukuhara.jp/collections/accessories"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 50,
    "total": 43,
    "total_pages": 1
  },
  "job_info": {
    "brand_name": "Jukuhara",
    "total_products": 43,
    "categories_processed": 6
  }
}
```

### 6. Download Results
```
GET /api/premium/scrape/<job_id>/download
```
Downloads the complete results as a CSV file.

### 7. List All Jobs
```
GET /api/premium/jobs?status=completed
```
Lists all scraping jobs with optional status filtering.

**Response:**
```json
{
  "success": true,
  "jobs": [...],
  "total": 1,
  "stats": {
    "running": 0,
    "completed": 1,
    "failed": 0
  }
}
```

## Architecture

### Components

1. **PremiumScraperAPI** (`/scraper_premium/api/premium_api.py`)
   - Main API class handling all endpoints
   - Job management and status tracking
   - Thread-safe operations

2. **ScrapingJob** 
   - Represents an ongoing scraping job
   - Tracks progress, status, and results
   - Provides real-time updates

3. **Integration with clean_api.py**
   - Seamlessly integrated with existing Flask app
   - Proper error handling and graceful fallbacks
   - No interference with existing endpoints

### Features

- **Asynchronous Processing**: Jobs run in background threads
- **Real-time Status**: Live progress tracking with detailed status updates
- **Intelligent Analysis**: LLM-powered pattern detection and navigation analysis
- **Scalable**: Can handle multiple concurrent scraping jobs
- **Error Handling**: Comprehensive error reporting and recovery
- **Data Export**: CSV download of complete results
- **Image Downloads**: Automatic product image downloading during scraping

## Example Usage

### Complete Brand Scraping Workflow

1. **Analyze Brand**:
   ```bash
   curl -X POST http://localhost:8081/api/premium/analyze \
        -H "Content-Type: application/json" \
        -d '{"brand_url": "https://jukuhara.jp"}'
   ```

2. **Start Scraping**:
   ```bash
   curl -X POST http://localhost:8081/api/premium/scrape \
        -H "Content-Type: application/json" \
        -d '{"brand_url": "https://jukuhara.jp", "brand_name": "Jukuhara"}'
   ```

3. **Monitor Progress**:
   ```bash
   curl -X GET http://localhost:8081/api/premium/scrape/scrape_1234567890
   ```

4. **Get Results**:
   ```bash
   curl -X GET "http://localhost:8081/api/premium/scrape/scrape_1234567890/products?page=1&per_page=10"
   ```

5. **Download CSV**:
   ```bash
   curl -X GET http://localhost:8081/api/premium/scrape/scrape_1234567890/download -o results.csv
   ```

## Performance

Based on testing with Jukuhara brand:
- **43 products** scraped from **6 categories** in **37.5 seconds**
- **Rate**: ~1.15 products/second including image downloads
- **Categories processed in parallel** with intelligent pattern fallback
- **Automatic image downloading** during scraping process

## Frontend Integration

The API is designed to work seamlessly with the existing React frontend in `/web_ui/`. Key integration points:

1. **Brand Analysis**: Check if a brand can be scraped before starting
2. **Job Management**: Start jobs and track progress with real-time updates
3. **Results Display**: Paginated product listings with search and filtering
4. **Export Features**: Download complete datasets as CSV
5. **Progress Tracking**: Live status updates during scraping

## Error Handling

The API includes comprehensive error handling:
- **Invalid URLs**: Automatic URL validation and correction
- **Network Issues**: Retry mechanisms and timeout handling  
- **Scraping Failures**: Graceful degradation with partial results
- **Pattern Detection**: Multi-pattern fallback system
- **Job Tracking**: Persistent job state even during API restarts

## Security Considerations

- **Rate Limiting**: Built-in delays to respect website resources
- **User Agent**: Proper browser identification
- **Robots.txt**: Respects website scraping policies
- **Resource Limits**: Prevents excessive resource usage
- **Input Validation**: Sanitizes all user inputs

## Next Steps

The premium scraper API is now ready for frontend integration. Recommended implementation:

1. Add premium scraper panel to React UI
2. Implement real-time job status updates
3. Create product browsing interface
4. Add search and filtering capabilities
5. Implement bulk export features