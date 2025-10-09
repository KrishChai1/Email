import email
import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from enum import Enum
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RoutingQueue(Enum):
    """Email routing queues based on UPS ORD & SF rules"""
    SHIPMENT_INITIATION_BRKG_INLAND_SI = "Shipment_Initiation_Brkg_Inland_SI"
    ACCOUNT_INQUIRY_US = "Account_Inquiry_US"
    ORD_SI_NON_UPS_SHIPMENTS = "ORD_SI-Non_UPS_Shipments"
    RAFT_PRE_ALERT = "RAFT_PreAlert"
    RAFT_ARRIVAL_NOTICE = "RAFT_ArrivalNotice"

class EmailRoutingAgent:
    """
    Complete Email Routing Agent for UPS ORD & SF Email to Case system
    Implements 5 routing rules with priority-based matching
    """
    
    def __init__(self):
        self.team_mailbox = "noreply-ordchbdocdesk@ups.com"
        self.distribution_list = "ordchbdocdesk@ups.com"
        self.salesforce_object = "scs.prod@8-ami9oibho94x2hn0tm7qhwd1apdfbd23ooe968owwrzislk71.hs-1rc8bmas.na236.case.salesforce.com"
        
        # Rule patterns for matching
        self.routing_rules = self._initialize_routing_rules()
        
        # Statistics tracking
        self.routing_stats = {
            "total_processed": 0,
            "rules_matched": {rule.value: 0 for rule in RoutingQueue},
            "processing_errors": 0
        }
    
    def _initialize_routing_rules(self) -> List[Dict]:
        """Initialize the 5 routing rules in priority order"""
        return [
            {
                "rule_id": 2,
                "queue": RoutingQueue.ACCOUNT_INQUIRY_US,
                "description": "Account Inquiry emails with specific terms in subject",
                "conditions": {
                    "subject_contains": [
                        "power of attorney", "poa", "account needed", "account setup"
                    ],
                    "check_attachments": True
                }
            },
            {
                "rule_id": 3,
                "queue": RoutingQueue.ORD_SI_NON_UPS_SHIPMENTS,
                "description": "Emails from Evergreen Line domain",
                "conditions": {
                    "from_domain": "@mail.evergreen-line.com"
                }
            },
            {
                "rule_id": 4,
                "queue": RoutingQueue.RAFT_PRE_ALERT,
                "description": "RAFT Pre-Alert emails",
                "conditions": {
                    "subject_contains": ["pre-alert", "pre alert", "prealert"]
                }
            },
            {
                "rule_id": 5,
                "queue": RoutingQueue.RAFT_ARRIVAL_NOTICE,
                "description": "RAFT Arrival Notice emails",
                "conditions": {
                    "subject_or_body_contains": ["arrival notice"]
                }
            },
            {
                "rule_id": 1,
                "queue": RoutingQueue.SHIPMENT_INITIATION_BRKG_INLAND_SI,
                "description": "Default rule - all other emails",
                "conditions": {
                    "default": True
                }
            }
        ]
    
    def parse_eml_file(self, eml_content: str) -> Dict:
        """Parse .eml file content and extract relevant information"""
        try:
            msg = email.message_from_string(eml_content)
            
            # Extract headers
            email_data = {
                "message_id": msg.get("Message-ID", ""),
                "from": msg.get("From", ""),
                "to": msg.get("To", ""),
                "cc": msg.get("Cc", ""),
                "subject": msg.get("Subject", ""),
                "date": msg.get("Date", ""),
                "reply_to": msg.get("Reply-To", ""),
                "priority": msg.get("X-Priority", ""),
                "body": "",
                "attachments": [],
                "is_html": False
            }
            
            # Extract body content
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        email_data["body"] += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    elif part.get_content_type() == "text/html":
                        email_data["body"] += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        email_data["is_html"] = True
                    elif part.get_filename():
                        email_data["attachments"].append(part.get_filename())
            else:
                email_data["body"] = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                if msg.get_content_type() == "text/html":
                    email_data["is_html"] = True
            
            return email_data
            
        except Exception as e:
            logger.error(f"Error parsing email: {str(e)}")
            raise
    
    def extract_from_domain(self, from_address: str) -> str:
        """Extract domain from email address"""
        try:
            # Handle "Name <email@domain.com>" format
            email_match = re.search(r'<([^>]+)>', from_address)
            if email_match:
                email_addr = email_match.group(1)
            else:
                email_addr = from_address.strip()
            
            # Extract domain
            domain_match = re.search(r'@([^@]+)', email_addr)
            return f"@{domain_match.group(1)}" if domain_match else ""
            
        except Exception as e:
            logger.warning(f"Error extracting domain from {from_address}: {str(e)}")
            return ""
    
    def check_text_contains(self, text: str, keywords: List[str]) -> bool:
        """Check if text contains any of the specified keywords (case-insensitive)"""
        if not text:
            return False
        
        text_lower = text.lower()
        return any(keyword.lower() in text_lower for keyword in keywords)
    
    def check_attachment_naming(self, attachments: List[str], keywords: List[str]) -> bool:
        """Check if any attachment names contain the specified keywords"""
        if not attachments:
            return False
        
        for attachment in attachments:
            if self.check_text_contains(attachment, keywords):
                return True
        return False
    
    def apply_routing_rule(self, email_data: Dict, rule: Dict) -> bool:
        """Apply a specific routing rule to the email data"""
        conditions = rule["conditions"]
        
        # Rule 2: Account Inquiry - Subject or attachment naming convention
        if "subject_contains" in conditions:
            subject_match = self.check_text_contains(email_data["subject"], conditions["subject_contains"])
            attachment_match = False
            
            if conditions.get("check_attachments", False):
                attachment_match = self.check_attachment_naming(
                    email_data["attachments"], 
                    conditions["subject_contains"]
                )
            
            if subject_match or attachment_match:
                logger.info(f"Rule {rule['rule_id']} matched: Account Inquiry (Subject: {subject_match}, Attachment: {attachment_match})")
                return True
        
        # Rule 3: Domain-based routing
        if "from_domain" in conditions:
            from_domain = self.extract_from_domain(email_data["from"])
            if from_domain == conditions["from_domain"]:
                logger.info(f"Rule {rule['rule_id']} matched: Domain routing ({from_domain})")
                return True
        
        # Rule 4: RAFT Pre-Alert - Subject only
        if "subject_contains" in conditions and rule["rule_id"] == 4:
            if self.check_text_contains(email_data["subject"], conditions["subject_contains"]):
                logger.info(f"Rule {rule['rule_id']} matched: RAFT Pre-Alert")
                return True
        
        # Rule 5: RAFT Arrival Notice - Subject or body
        if "subject_or_body_contains" in conditions:
            keywords = conditions["subject_or_body_contains"]
            subject_match = self.check_text_contains(email_data["subject"], keywords)
            body_match = self.check_text_contains(email_data["body"], keywords)
            
            if subject_match or body_match:
                logger.info(f"Rule {rule['rule_id']} matched: RAFT Arrival Notice (Subject: {subject_match}, Body: {body_match})")
                return True
        
        # Rule 1: Default rule (always matches)
        if conditions.get("default", False):
            logger.info(f"Rule {rule['rule_id']} matched: Default routing")
            return True
        
        return False
    
    def route_email(self, eml_content: str) -> Dict:
        """
        Main routing function - processes email and determines routing queue
        Returns routing decision with detailed information
        """
        try:
            # Parse email
            email_data = self.parse_eml_file(eml_content)
            
            # Apply routing rules in priority order
            for rule in self.routing_rules:
                if self.apply_routing_rule(email_data, rule):
                    routing_result = {
                        "routing_queue": rule["queue"].value,
                        "rule_matched": rule["rule_id"],
                        "rule_description": rule["description"],
                        "email_data": email_data,
                        "routing_timestamp": datetime.now().isoformat(),
                        "confidence": "HIGH" if rule["rule_id"] != 1 else "DEFAULT"
                    }
                    
                    # Update statistics
                    self.routing_stats["total_processed"] += 1
                    self.routing_stats["rules_matched"][rule["queue"].value] += 1
                    
                    logger.info(f"Email routed to: {rule['queue'].value} (Rule {rule['rule_id']})")
                    return routing_result
            
            # This should never happen due to default rule, but safety fallback
            raise Exception("No routing rule matched - this should not happen!")
            
        except Exception as e:
            self.routing_stats["processing_errors"] += 1
            logger.error(f"Routing error: {str(e)}")
            raise
    
    def batch_process_emails(self, eml_files: List[str]) -> List[Dict]:
        """Process multiple email files and return routing results"""
        results = []
        
        for i, eml_content in enumerate(eml_files):
            try:
                logger.info(f"Processing email {i+1}/{len(eml_files)}")
                result = self.route_email(eml_content)
                results.append(result)
            except Exception as e:
                error_result = {
                    "error": str(e),
                    "email_index": i,
                    "routing_timestamp": datetime.now().isoformat()
                }
                results.append(error_result)
        
        return results
    
    def get_routing_statistics(self) -> Dict:
        """Get routing statistics and performance metrics"""
        return {
            "statistics": self.routing_stats.copy(),
            "rules_configuration": [
                {
                    "rule_id": rule["rule_id"],
                    "queue": rule["queue"].value,
                    "description": rule["description"]
                }
                for rule in self.routing_rules
            ],
            "generated_at": datetime.now().isoformat()
        }
    
    def validate_routing_configuration(self) -> Dict:
        """Validate that all routing rules are properly configured"""
        validation_results = {
            "is_valid": True,
            "issues": [],
            "warnings": []
        }
        
        # Check if default rule exists
        default_rules = [rule for rule in self.routing_rules if rule["conditions"].get("default")]
        if len(default_rules) != 1:
            validation_results["is_valid"] = False
            validation_results["issues"].append("Exactly one default rule is required")
        
        # Check for duplicate rule IDs
        rule_ids = [rule["rule_id"] for rule in self.routing_rules]
        if len(rule_ids) != len(set(rule_ids)):
            validation_results["is_valid"] = False
            validation_results["issues"].append("Duplicate rule IDs found")
        
        # Check if all queues are covered
        covered_queues = {rule["queue"] for rule in self.routing_rules}
        all_queues = set(RoutingQueue)
        missing_queues = all_queues - covered_queues
        if missing_queues:
            validation_results["warnings"].append(f"Some queues not covered: {[q.value for q in missing_queues]}")
        
        return validation_results

# Example usage and testing functions
def test_routing_agent():
    """Test the routing agent with sample emails"""
    
    # Initialize agent
    agent = EmailRoutingAgent()
    
    # Validate configuration
    validation = agent.validate_routing_configuration()
    print("Configuration Validation:", json.dumps(validation, indent=2))
    
    # Test emails for each rule
    test_emails = [
        # Rule 2: Account Inquiry
        """From: customer@example.com
To: ordchbdocdesk@ups.com
Subject: Need Account Setup for New Business
Date: Thu, 09 Oct 2025 10:00:00 +0000

I need help setting up a new account for my business.""",
        
        # Rule 3: Evergreen Line
        """From: shipping@mail.evergreen-line.com
To: ordchbdocdesk@ups.com
Subject: Shipment Update EMC-12345
Date: Thu, 09 Oct 2025 11:00:00 +0000

Container shipment details attached.""",
        
        # Rule 4: RAFT Pre-Alert
        """From: logistics@terminal.com
To: ordchbdocdesk@ups.com
Subject: Pre-Alert Notification - Vessel ETA Tomorrow
Date: Thu, 09 Oct 2025 12:00:00 +0000

Pre-alert for incoming vessel.""",
        
        # Rule 5: RAFT Arrival Notice
        """From: port@harbor.com
To: ordchbdocdesk@ups.com
Subject: Container Status Update
Date: Thu, 09 Oct 2025 13:00:00 +0000

This is an arrival notice for your container shipment.""",
        
        # Rule 1: Default
        """From: vendor@supplier.com
To: ordchbdocdesk@ups.com
Subject: Invoice Payment Question
Date: Thu, 09 Oct 2025 14:00:00 +0000

Question about recent invoice."""
    ]
    
    # Process test emails
    print("\n=== ROUTING TEST RESULTS ===")
    for i, email_content in enumerate(test_emails):
        try:
            result = agent.route_email(email_content)
            print(f"\nEmail {i+1}:")
            print(f"  Queue: {result['routing_queue']}")
            print(f"  Rule: {result['rule_matched']} - {result['rule_description']}")
            print(f"  Subject: {result['email_data']['subject']}")
        except Exception as e:
            print(f"Email {i+1} Error: {e}")
    
    # Print statistics
    print("\n=== ROUTING STATISTICS ===")
    stats = agent.get_routing_statistics()
    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    test_routing_agent()
