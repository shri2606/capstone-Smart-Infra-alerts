#!/bin/bash

echo "Starting Enhanced IntelliAlert Setup"
echo "===================================="

echo "Checking if Docker is running..."
if ! docker --version > /dev/null 2>&1; then
    echo "ERROR: Docker is not installed or not running"
    exit 1
fi

echo "Checking Docker Compose availability..."
# Check for Docker Compose V2 first (preferred)
if docker compose version > /dev/null 2>&1; then
    echo "Using Docker Compose V2 (docker compose)"
    COMPOSE_CMD="docker compose"
elif docker-compose --version > /dev/null 2>&1; then
    echo "Using Docker Compose V1 (docker-compose)"
    COMPOSE_CMD="docker-compose"
else
    echo "ERROR: No Docker Compose found. Please install Docker Compose."
    echo "Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "Building and starting services..."
$COMPOSE_CMD up --build -d

echo "Waiting for services to start..."
echo "This may take 1-2 minutes for first-time setup..."

# Function to check service health
check_service() {
    local url=$1
    local name=$2
    local max_attempts=30
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s "$url" > /dev/null 2>&1; then
            echo "✅ $name is healthy"
            return 0
        fi
        echo "⏳ Waiting for $name... (attempt $attempt/$max_attempts)"
        sleep 10
        ((attempt++))
    done
    
    echo "❌ $name failed to start after $((max_attempts * 10)) seconds"
    return 1
}

echo ""
echo "Testing service endpoints..."

# Test services in dependency order
check_service "http://localhost:9090/-/healthy" "Prometheus"
prometheus_status=$?

check_service "http://localhost:3100/ready" "Loki"
loki_status=$?

check_service "http://localhost:9093/-/healthy" "Alertmanager"
alertmanager_status=$?

check_service "http://localhost:8000/metrics" "Incident Generator"
generator_status=$?

echo ""
echo "Service Status Summary:"
echo "======================"

# Display results
if [ $prometheus_status -eq 0 ]; then
    echo "✅ Prometheus:        http://localhost:9090"
else
    echo "❌ Prometheus:        FAILED"
fi

if [ $alertmanager_status -eq 0 ]; then
    echo "✅ Alertmanager:      http://localhost:9093"
else
    echo "❌ Alertmanager:      FAILED"
fi

if [ $loki_status -eq 0 ]; then
    echo "✅ Loki:             http://localhost:3100"
else
    echo "❌ Loki:             FAILED"
fi

if [ $generator_status -eq 0 ]; then
    echo "✅ Incident Generator: http://localhost:8000/metrics"
else
    echo "❌ Incident Generator: FAILED"
fi

echo ""

# Check if any services failed
total_failures=$((4 - prometheus_status - loki_status - alertmanager_status - generator_status))

if [ $total_failures -eq 0 ]; then
    echo "🎉 All services started successfully!"
    
    echo ""
    echo "Testing data collection..."
    
    # Test metrics collection
    echo "📊 Testing metrics collection..."
    sleep 5  # Give generator time to produce metrics
    METRIC_COUNT=$(curl -s http://localhost:8000/metrics | grep -c "service_" 2>/dev/null || echo "0")
    if [ "$METRIC_COUNT" -gt 0 ]; then
        echo "✅ Found $METRIC_COUNT service metrics"
    else
        echo "⚠️  No service metrics found yet (may take a minute)"
    fi
    
    # Test Prometheus targets
    echo "🎯 Testing Prometheus targets..."
    TARGET_STATUS=$(curl -s "http://localhost:9090/api/v1/targets" | grep -o '"health":"[^"]*"' | head -1 2>/dev/null || echo "")
    if [[ "$TARGET_STATUS" == *"up"* ]]; then
        echo "✅ Prometheus targets are healthy"
    else
        echo "⚠️  Prometheus targets not ready yet"
    fi
    
    # Test log collection (may take longer)
    echo "📝 Testing log collection..."
    LOG_QUERY=$(curl -s "http://localhost:3100/loki/api/v1/query?query={service=~\".*\"}&limit=1" 2>/dev/null || echo "")
    if [[ "$LOG_QUERY" == *"values"* ]]; then
        echo "✅ Logs are being collected in Loki"
    else
        echo "⚠️  No logs found yet (this is normal, may take 2-3 minutes)"
    fi
    
    echo ""
    echo "🎯 Monitoring Incidents:"
    echo "========================"
    echo "Watch live incident generation:"
    echo "  $COMPOSE_CMD logs -f enhanced-incident-generator"
    echo ""
    echo "Check Prometheus alerts:"
    echo "  Open http://localhost:9090 → Alerts tab"
    echo ""
    echo "View incident metrics:"
    echo "  Open http://localhost:9090 → Graph tab"
    echo "  Query: service_memory_usage"
    echo ""
    echo "Query logs:"
    echo "  curl \"http://localhost:3100/loki/api/v1/query?query={service=\\\"user-api\\\"}\""
    echo ""
    echo "✅ Setup completed successfully!"
    
else
    echo "❌ $total_failures service(s) failed to start"
    echo ""
    echo "Troubleshooting:"
    echo "==============="
    echo "Check logs with:"
    echo "  $COMPOSE_CMD logs"
    echo ""
    echo "Check individual service logs:"
    echo "  $COMPOSE_CMD logs prometheus"
    echo "  $COMPOSE_CMD logs loki"
    echo "  $COMPOSE_CMD logs alertmanager"
    echo "  $COMPOSE_CMD logs enhanced-incident-generator"
    echo ""
    echo "Restart services:"
    echo "  $COMPOSE_CMD down"
    echo "  $COMPOSE_CMD up --build"
    echo ""
    echo "Check container status:"
    echo "  $COMPOSE_CMD ps"
    
    exit 1
fi

echo ""
echo "🔧 Useful Commands:"
echo "=================="
echo "Stop services:           $COMPOSE_CMD down"
echo "View logs:              $COMPOSE_CMD logs -f"
echo "Restart services:       $COMPOSE_CMD restart"
echo "Check status:           $COMPOSE_CMD ps"
echo "Clean restart:          $COMPOSE_CMD down -v && $COMPOSE_CMD up --build"
echo ""
echo "Happy monitoring! 🚀