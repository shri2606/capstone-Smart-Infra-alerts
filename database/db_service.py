"""
IntelliAlert Database Service
Handles PostgreSQL connections and operations for incident tracking
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Union
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import RealDictCursor, Json
import uuid

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseConnectionError(Exception):
    """Custom exception for database connection issues"""
    pass

class DatabaseService:
    """
    PostgreSQL database service for IntelliAlert
    Handles connections, connection pooling, and database operations
    """
    
    def __init__(self):
        self.connection_pool = None
        self._load_config()
        self._create_connection_pool()
    
    def _load_config(self):
        """Load database configuration from environment variables"""
        try:
            # Load from .env file if available
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                logger.warning("python-dotenv not installed, using system environment variables only")
            
            self.config = {
                'host': os.getenv('POSTGRES_HOST', 'localhost'),
                'port': int(os.getenv('POSTGRES_PORT', 5432)),
                'database': os.getenv('POSTGRES_DB'),
                'user': os.getenv('POSTGRES_USER'),
                'password': os.getenv('POSTGRES_PASSWORD'),
                'min_conn': int(os.getenv('DB_POOL_MIN_CONN', 1)),
                'max_conn': int(os.getenv('DB_POOL_MAX_CONN', 10))
            }
            
            # Validate required configuration
            required_fields = ['database', 'user', 'password']
            missing_fields = [field for field in required_fields if not self.config[field]]
            
            if missing_fields:
                raise DatabaseConnectionError(
                    f"Missing required environment variables: {', '.join(missing_fields.upper())}. "
                    "Please check your .env file or environment variables."
                )
                
        except Exception as e:
            logger.error(f"Error loading database configuration: {e}")
            raise DatabaseConnectionError(f"Configuration error: {e}")
    
    def _create_connection_pool(self):
        """Create connection pool for database operations"""
        try:
            self.connection_pool = psycopg2.pool.SimpleConnectionPool(
                self.config['min_conn'],
                self.config['max_conn'],
                host=self.config['host'],
                port=self.config['port'],
                database=self.config['database'],
                user=self.config['user'],
                password=self.config['password'],
                cursor_factory=RealDictCursor
            )
            logger.info("Database connection pool created successfully")
            
        except Exception as e:
            logger.error(f"Error creating connection pool: {e}")
            raise DatabaseConnectionError(f"Failed to create connection pool: {e}")
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = None
        try:
            conn = self.connection_pool.getconn()
            if conn:
                yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                self.connection_pool.putconn(conn)
    
    def test_connection(self) -> bool:
        """Test database connection"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1 as test")
                    result = cursor.fetchone()
                    if result:
                        # Handle RealDictRow access
                        return result['test'] == 1
                    return False
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    def create_incident(self, incident_type: str, service_name: str, severity: str, 
                       description: str = None, affected_pods: List[str] = None) -> str:
        """Create a new incident and return its ID"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    incident_id = str(uuid.uuid4())
                    cursor.execute(
                        """
                        INSERT INTO incidents (id, incident_type, service_name, severity, description, affected_pods)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (incident_id, incident_type, service_name, severity, description, affected_pods)
                    )
                    conn.commit()
                    result = cursor.fetchone()
                    logger.info(f"Created incident {result['id']} for service {service_name}")
                    return str(result['id'])
                    
        except Exception as e:
            logger.error(f"Error creating incident: {e}")
            raise
    
    def update_incident_status(self, incident_id: str, status: str, end_time: datetime = None):
        """Update incident status and optionally set end time"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE incidents 
                        SET status = %s, end_time = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (status, end_time, incident_id)
                    )
                    conn.commit()
                    logger.info(f"Updated incident {incident_id} status to {status}")
                    
        except Exception as e:
            logger.error(f"Error updating incident status: {e}")
            raise
    
    def insert_metric(self, service_name: str, pod_name: str, metric_name: str, 
                     metric_value: float, incident_id: str = None, labels: Dict = None):
        """Insert a metric data point"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO metrics (service_name, pod_name, metric_name, metric_value, incident_id, labels)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (service_name, pod_name, metric_name, metric_value, incident_id, Json(labels) if labels else None)
                    )
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"Error inserting metric: {e}")
            raise
    
    def insert_log(self, service_name: str, pod_name: str, log_level: str, 
                   message: str, incident_id: str = None, labels: Dict = None):
        """Insert a log entry"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO logs (service_name, pod_name, log_level, message, incident_id, labels)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (service_name, pod_name, log_level, message, incident_id, Json(labels) if labels else None)
                    )
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"Error inserting log: {e}")
            raise
    
    def insert_alert(self, alert_name: str, service_name: str, severity: str, 
                    status: str, starts_at: datetime, ends_at: datetime = None,
                    incident_id: str = None, labels: Dict = None, annotations: Dict = None):
        """Insert an alert"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO alerts (alert_name, service_name, severity, status, starts_at, ends_at, incident_id, labels, annotations)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (alert_name, service_name, severity, status, starts_at, ends_at, incident_id, 
                         Json(labels) if labels else None, Json(annotations) if annotations else None)
                    )
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"Error inserting alert: {e}")
            raise
    
    def get_active_incidents(self) -> List[Dict]:
        """Get all active incidents"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM get_active_incidents()")
                    return [dict(row) for row in cursor.fetchall()]
                    
        except Exception as e:
            logger.error(f"Error getting active incidents: {e}")
            return []
    
    def get_incident_summary(self, incident_id: str) -> Dict:
        """Get comprehensive incident summary"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM get_incident_summary(%s)", (incident_id,))
                    result = cursor.fetchone()
                    return dict(result) if result else {}
                    
        except Exception as e:
            logger.error(f"Error getting incident summary: {e}")
            return {}
    
    def get_service_health(self) -> List[Dict]:
        """Get service health summary"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM service_health_summary")
                    return [dict(row) for row in cursor.fetchall()]
                    
        except Exception as e:
            logger.error(f"Error getting service health: {e}")
            return []
    
    def execute_query(self, query: str, params: tuple = None) -> List[Dict]:
        """Execute a custom query and return results"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    return [dict(row) for row in cursor.fetchall()]
                    
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            return []
    
    def close(self):
        """Close all connections in the pool"""
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("Database connection pool closed")

# Global database service instance
db_service = None

def get_db_service() -> DatabaseService:
    """Get or create database service instance"""
    global db_service
    if db_service is None:
        db_service = DatabaseService()
    return db_service

def initialize_database():
    """Initialize database service and test connection"""
    try:
        service = get_db_service()
        if service.test_connection():
            logger.info("Database service initialized successfully")
            return True
        else:
            logger.error("Database connection test failed")
            return False
    except Exception as e:
        logger.error(f"Failed to initialize database service: {e}")
        return False

# Example usage and testing
if __name__ == "__main__":
    # Test the database service
    try:
        print("Testing database service...")
        service = DatabaseService()
        
        if service.test_connection():
            print("Database connection successful")
            
            # Test creating an incident
            incident_id = service.create_incident(
                incident_type="TestIncident",
                service_name="test-service",
                severity="medium",
                description="Test incident for database service",
                affected_pods=["test-pod-1"]
            )
            print(f"Created test incident: {incident_id}")
            
            # Test inserting a metric
            service.insert_metric(
                service_name="test-service",
                pod_name="test-pod-1",
                metric_name="cpu_usage",
                metric_value=75.5,
                incident_id=incident_id,
                labels={"environment": "test"}
            )
            print("Inserted test metric")
            
            # Test inserting a log
            service.insert_log(
                service_name="test-service",
                pod_name="test-pod-1",
                log_level="INFO",
                message="Test log message",
                incident_id=incident_id,
                labels={"component": "test"}
            )
            print("Inserted test log")
            
            # Get active incidents
            incidents = service.get_active_incidents()
            print(f"Found {len(incidents)} active incidents")
            
            # Clean up test incident
            service.update_incident_status(incident_id, "resolved", datetime.now(timezone.utc))
            print("Resolved test incident")
            
        else:
            print("Database connection failed")
            
    except Exception as e:
        print(f"Database service test failed: {e}")
        print("Please check your .env file and ensure PostgreSQL is running")