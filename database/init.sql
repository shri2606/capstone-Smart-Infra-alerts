-- IntelliAlert Database Schema
-- PostgreSQL initialization script for incident tracking and observability data

-- Create database (run manually if needed)
-- CREATE DATABASE intellialert;
-- \c intellialert;

-- Create extensions for better performance and functionality
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- Create enum types for better data integrity
CREATE TYPE incident_status AS ENUM ('active', 'resolved', 'investigating', 'acknowledged');
CREATE TYPE severity_level AS ENUM ('critical', 'high', 'medium', 'low', 'info');
CREATE TYPE log_level AS ENUM ('ERROR', 'WARN', 'INFO', 'DEBUG', 'TRACE');
CREATE TYPE alert_status AS ENUM ('firing', 'resolved', 'pending');

-- Incidents table - Main incident tracking
CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_type VARCHAR(100) NOT NULL,
    service_name VARCHAR(100) NOT NULL,
    severity severity_level NOT NULL,
    status incident_status NOT NULL DEFAULT 'active',
    start_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    end_time TIMESTAMP WITH TIME ZONE,
    affected_pods TEXT[],
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Metrics table - Time-series metrics data linked to incidents
CREATE TABLE metrics (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    service_name VARCHAR(100) NOT NULL,
    pod_name VARCHAR(100),
    metric_name VARCHAR(100) NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
    labels JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Logs table - Application logs linked to incidents  
CREATE TABLE logs (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    service_name VARCHAR(100) NOT NULL,
    pod_name VARCHAR(100),
    log_level log_level NOT NULL,
    message TEXT NOT NULL,
    incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
    labels JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Alerts table - Alert manager alerts linked to incidents
CREATE TABLE alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_name VARCHAR(200) NOT NULL,
    service_name VARCHAR(100) NOT NULL,
    severity severity_level NOT NULL,
    status alert_status NOT NULL,
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ends_at TIMESTAMP WITH TIME ZONE,
    incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
    labels JSONB,
    annotations JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX idx_incidents_service_name ON incidents(service_name);
CREATE INDEX idx_incidents_status ON incidents(status);
CREATE INDEX idx_incidents_start_time ON incidents(start_time);
CREATE INDEX idx_incidents_severity ON incidents(severity);

CREATE INDEX idx_metrics_timestamp ON metrics(timestamp);
CREATE INDEX idx_metrics_service_name ON metrics(service_name);
CREATE INDEX idx_metrics_incident_id ON metrics(incident_id);
CREATE INDEX idx_metrics_metric_name ON metrics(metric_name);
CREATE INDEX idx_metrics_service_timestamp ON metrics(service_name, timestamp);

CREATE INDEX idx_logs_timestamp ON logs(timestamp);
CREATE INDEX idx_logs_service_name ON logs(service_name);
CREATE INDEX idx_logs_incident_id ON logs(incident_id);
CREATE INDEX idx_logs_log_level ON logs(log_level);
CREATE INDEX idx_logs_service_timestamp ON logs(service_name, timestamp);

CREATE INDEX idx_alerts_service_name ON alerts(service_name);
CREATE INDEX idx_alerts_status ON alerts(status);
CREATE INDEX idx_alerts_incident_id ON alerts(incident_id);
CREATE INDEX idx_alerts_starts_at ON alerts(starts_at);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at trigger to relevant tables
CREATE TRIGGER update_incidents_updated_at BEFORE UPDATE ON incidents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_alerts_updated_at BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Helper function to get active incidents
CREATE OR REPLACE FUNCTION get_active_incidents()
RETURNS TABLE(
    incident_id UUID,
    service_name VARCHAR,
    severity severity_level,
    start_time TIMESTAMP WITH TIME ZONE,
    description TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT i.id, i.service_name, i.severity, i.start_time, i.description
    FROM incidents i
    WHERE i.status = 'active'
    ORDER BY i.start_time DESC;
END;
$$ LANGUAGE plpgsql;

-- Helper function to get incident summary
CREATE OR REPLACE FUNCTION get_incident_summary(incident_uuid UUID)
RETURNS TABLE(
    incident_info JSON,
    metrics_count BIGINT,
    logs_count BIGINT,
    alerts_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        row_to_json(i.*) as incident_info,
        (SELECT COUNT(*) FROM metrics m WHERE m.incident_id = incident_uuid) as metrics_count,
        (SELECT COUNT(*) FROM logs l WHERE l.incident_id = incident_uuid) as logs_count,
        (SELECT COUNT(*) FROM alerts a WHERE a.incident_id = incident_uuid) as alerts_count
    FROM incidents i
    WHERE i.id = incident_uuid;
END;
$$ LANGUAGE plpgsql;

-- Create a view for incident overview
CREATE VIEW incident_overview AS
SELECT 
    i.id,
    i.service_name,
    i.incident_type,
    i.severity,
    i.status,
    i.start_time,
    i.end_time,
    EXTRACT(EPOCH FROM (COALESCE(i.end_time, NOW()) - i.start_time)) as duration_seconds,
    array_length(i.affected_pods, 1) as affected_pods_count,
    (SELECT COUNT(*) FROM metrics m WHERE m.incident_id = i.id) as metrics_count,
    (SELECT COUNT(*) FROM logs l WHERE l.incident_id = i.id) as logs_count,
    (SELECT COUNT(*) FROM alerts a WHERE a.incident_id = i.id) as alerts_count
FROM incidents i;

-- Create a view for service health summary
CREATE VIEW service_health_summary AS
SELECT 
    service_name,
    COUNT(*) FILTER (WHERE status = 'active') as active_incidents,
    COUNT(*) FILTER (WHERE status = 'resolved') as resolved_incidents,
    COUNT(*) FILTER (WHERE severity = 'critical') as critical_incidents,
    COUNT(*) FILTER (WHERE severity = 'high') as high_incidents,
    MAX(start_time) as last_incident_time
FROM incidents
GROUP BY service_name;

-- Insert some example data for testing
INSERT INTO incidents (incident_type, service_name, severity, status, description, affected_pods) VALUES
('HighMemoryUsage', 'user-api', 'high', 'active', 'Memory usage exceeded 80% threshold', ARRAY['user-api-pod-1', 'user-api-pod-2']),
('DatabaseConnectionFailure', 'order-service', 'critical', 'investigating', 'Unable to connect to primary database', ARRAY['order-service-pod-1']),
('SlowResponseTime', 'payment-gateway', 'medium', 'resolved', 'API response time exceeded 2 seconds', ARRAY['payment-gateway-pod-1']);

-- Create database user and grant permissions (to be run manually by admin)
-- CREATE USER intellialert_user WITH PASSWORD 'secure_dev_password_123';
-- GRANT CONNECT ON DATABASE intellialert TO intellialert_user;
-- GRANT USAGE ON SCHEMA public TO intellialert_user;
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO intellialert_user;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO intellialert_user;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO intellialert_user;

-- Comments for documentation
COMMENT ON TABLE incidents IS 'Main table for tracking incidents and their lifecycle';
COMMENT ON TABLE metrics IS 'Time-series metrics data linked to incidents for correlation';
COMMENT ON TABLE logs IS 'Application logs linked to incidents for debugging';
COMMENT ON TABLE alerts IS 'Alert manager alerts linked to incidents for notification tracking';
COMMENT ON VIEW incident_overview IS 'Comprehensive view of incidents with related data counts';
COMMENT ON VIEW service_health_summary IS 'Summary of service health across all incidents';