#!/bin/bash

# Test Script für SSRF Protection
# Testet ob die Input Validation funktioniert

API_URL="${API_URL:-http://localhost:8000}"

echo "🧪 Testing SSRF Protection..."
echo "API URL: $API_URL"
echo ""

# Test 1: Localhost sollte blockiert werden
echo "Test 1: Localhost (should BLOCK)"
curl -s -X POST "$API_URL/api/scan" \
  -H "Content-Type: application/json" \
  -d '{"url":"http://localhost:8000/admin"}' | jq -r '.detail.error.code // "OK"'
echo ""

# Test 2: 127.0.0.1 sollte blockiert werden
echo "Test 2: 127.0.0.1 (should BLOCK)"
curl -s -X POST "$API_URL/api/scan" \
  -H "Content-Type: application/json" \
  -d '{"url":"http://127.0.0.1:8000"}' | jq -r '.detail.error.code // "OK"'
echo ""

# Test 3: AWS Metadata sollte blockiert werden
echo "Test 3: AWS Metadata (should BLOCK)"
curl -s -X POST "$API_URL/api/scan" \
  -H "Content-Type: application/json" \
  -d '{"url":"http://169.254.169.254/latest/meta-data/"}' | jq -r '.detail.error.code // "OK"'
echo ""

# Test 4: Private IP sollte blockiert werden
echo "Test 4: Private IP 192.168.1.1 (should BLOCK)"
curl -s -X POST "$API_URL/api/scan" \
  -H "Content-Type: application/json" \
  -d '{"url":"http://192.168.1.1"}' | jq -r '.detail.error.code // "OK"'
echo ""

# Test 5: Private IP 10.x sollte blockiert werden
echo "Test 5: Private IP 10.0.0.1 (should BLOCK)"
curl -s -X POST "$API_URL/api/scan" \
  -H "Content-Type: application/json" \
  -d '{"url":"http://10.0.0.1"}' | jq -r '.detail.error.code // "OK"'
echo ""

# Test 6: Ungültiges Schema sollte blockiert werden
echo "Test 6: Invalid scheme (should BLOCK)"
curl -s -X POST "$API_URL/api/scan" \
  -H "Content-Type: application/json" \
  -d '{"url":"javascript:alert(1)"}' | jq -r '.detail.error.code // "OK"'
echo ""

# Test 7: Valide URL sollte erlaubt sein
echo "Test 7: Valid URL example.com (should ALLOW)"
curl -s -X POST "$API_URL/api/scan" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}' | jq -r '.ok // .detail.error.code'
echo ""

echo "✅ Tests completed!"
echo ""
echo "Expected Results:"
echo "  Tests 1-6: SHOULD show error codes (LOCALHOST_NOT_ALLOWED, PRIVATE_IP_NOT_ALLOWED, etc.)"
echo "  Test 7: SHOULD start scan (ok=true or scanning)"
