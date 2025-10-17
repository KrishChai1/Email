import streamlit as st
import email
import re
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum
import base64
import os
from io import BytesIO

# Page config
st.set_page_config(
    page_title="BEAM - Brokerage Email Automation Manager",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #8B4513 0%, #D2691E 100%);
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    .main-header h1 {
        color: white;
        margin: 0;
        text-align: center;
    }
    .metric-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #8B4513;
        margin: 0.5rem 0;
    }
    .routing-result {
        background: #e8f5e9;
        padding: 1.5rem;
        border-radius: 8px;
        border: 2px solid #4caf50;
        margin: 1rem 0;
    }
    .action-box {
        background: #e3f2fd;
        padding: 1.5rem;
        border-radius: 8px;
        border: 2px solid #2196f3;
        margin: 1rem 0;
    }
    .warning-box {
        background: #fff3cd;
        border: 1px solid #ffeaa7;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    .error-box {
        background: #f8d7da;
        border: 1px solid #f5c6cb;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    .rule-box {
        background: #fff9c4;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #ff9800;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Routing Queue Enum
class RoutingQueue(Enum):
    SHIPMENT_INITIATION_BRKG_INLAND_SI = "Shipment_Initiation_Brkg_Inland_SI"
    ACCOUNT_INQUIRY_US = "Account_Inquiry_US"
    ORD_SI_NON_UPS_SHIPMENTS = "ORD_SI-Non_UPS_Shipments"
    RAFT_PRE_ALERT = "RAFT_PreAlert"
    RAFT_ARRIVAL_NOTICE = "RAFT_ArrivalNotice"

class EmailRoutingAgent:
    """Email Routing Agent for UPS ORD & SF system"""
    
    def __init__(self):
        self.team_mailbox = "noreply-ordchbdocdesk@ups.com"
        self.distribution_list = "ordchbdocdesk@ups.com"
        self.routing_rules = self._initialize_routing_rules()
        self.routing_stats = {
            "total_processed": 0,
            "rules_matched": {rule.value: 0 for rule in RoutingQueue},
        }
    
    def _initialize_routing_rules(self) -> List[Dict]:
        return [
            {
                "rule_id": 2,
                "queue": RoutingQueue.ACCOUNT_INQUIRY_US,
                "description": "Account Inquiry emails with specific terms",
                "scenario": "Customer Account Setup/POA Request",
                "action": "Route to Account Management Team for customer onboarding or Power of Attorney processing",
                "priority": "HIGH",
                "sla": "4 hours",
                "conditions": {
                    "subject_contains": ["power of attorney", "poa", "account needed", "account setup"],
                    "check_attachments": True
                }
            },
            {
                "rule_id": 3,
                "queue": RoutingQueue.ORD_SI_NON_UPS_SHIPMENTS,
                "description": "Emails from Evergreen Line domain",
                "scenario": "External Shipping Partner Communication",
                "action": "Process as non-UPS shipment documentation from Evergreen Marine",
                "priority": "MEDIUM",
                "sla": "8 hours",
                "conditions": {
                    "from_domain": "@mail.evergreen-line.com"
                }
            },
            {
                "rule_id": 4,
                "queue": RoutingQueue.RAFT_PRE_ALERT,
                "description": "RAFT Pre-Alert emails",
                "scenario": "Vessel/Container Pre-Alert Notification",
                "action": "Prepare for incoming container arrival, notify warehouse teams",
                "priority": "HIGH",
                "sla": "2 hours",
                "conditions": {
                    "subject_contains": ["pre-alert", "pre alert", "prealert"]
                }
            },
            {
                "rule_id": 5,
                "queue": RoutingQueue.RAFT_ARRIVAL_NOTICE,
                "description": "RAFT Arrival Notice emails",
                "scenario": "Container/Shipment Arrival Confirmation",
                "action": "Update tracking systems, notify customers, coordinate pickup scheduling",
                "priority": "HIGH", 
                "sla": "1 hour",
                "conditions": {
                    "subject_or_body_contains": ["arrival notice"]
                }
            },
            {
                "rule_id": 1,
                "queue": RoutingQueue.SHIPMENT_INITIATION_BRKG_INLAND_SI,
                "description": "Default rule - all other emails",
                "scenario": "General Shipment/Logistics Communication",
                "action": "Process as standard shipment initiation or brokerage inland SI request",
                "priority": "NORMAL",
                "sla": "24 hours",
                "conditions": {
                    "default": True
                }
            }
        ]
    
    def parse_eml_file(self, eml_content: str) -> Dict:
        """Parse .eml or .msg file content"""
        try:
            msg = email.message_from_string(eml_content)
            
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
            st.error(f"Error parsing email file: {str(e)}")
            st.info("💡 Note: .msg files work best when converted to .eml format first")
            return {}
    
    def extract_from_domain(self, from_address: str) -> str:
        """Extract domain from email address"""
        try:
            email_match = re.search(r'<([^>]+)>', from_address)
            if email_match:
                email_addr = email_match.group(1)
            else:
                email_addr = from_address.strip()
            
            domain_match = re.search(r'@([^@]+)', email_addr)
            return f"@{domain_match.group(1)}" if domain_match else ""
            
        except Exception:
            return ""
    
    def check_text_contains(self, text: str, keywords: List[str]) -> bool:
        """Check if text contains any keywords (case-insensitive)"""
        if not text:
            return False
        text_lower = text.lower()
        return any(keyword.lower() in text_lower for keyword in keywords)
    
    def check_attachment_naming(self, attachments: List[str], keywords: List[str]) -> bool:
        """Check if attachment names contain keywords"""
        if not attachments:
            return False
        for attachment in attachments:
            if self.check_text_contains(attachment, keywords):
                return True
        return False
    
    def apply_routing_rule(self, email_data: Dict, rule: Dict) -> tuple:
        """Apply specific routing rule and return (matched, reason)"""
        conditions = rule["conditions"]
        
        # Rule 2: Account Inquiry
        if "subject_contains" in conditions and rule["rule_id"] == 2:
            subject_match = self.check_text_contains(email_data["subject"], conditions["subject_contains"])
            attachment_match = False
            
            if conditions.get("check_attachments", False):
                attachment_match = self.check_attachment_naming(
                    email_data["attachments"], conditions["subject_contains"]
                )
            
            if subject_match:
                return True, f"Subject contains account-related keywords: {conditions['subject_contains']}"
            elif attachment_match:
                return True, f"Attachment names contain account-related keywords"
            return False, ""
        
        # Rule 3: Domain-based routing  
        if "from_domain" in conditions:
            from_domain = self.extract_from_domain(email_data["from"])
            if from_domain == conditions["from_domain"]:
                return True, f"Email from Evergreen Line domain: {from_domain}"
            return False, f"Domain {from_domain} does not match {conditions['from_domain']}"
        
        # Rule 4: RAFT Pre-Alert
        if "subject_contains" in conditions and rule["rule_id"] == 4:
            if self.check_text_contains(email_data["subject"], conditions["subject_contains"]):
                return True, f"Subject contains pre-alert keywords: {conditions['subject_contains']}"
            return False, ""
        
        # Rule 5: RAFT Arrival Notice
        if "subject_or_body_contains" in conditions:
            keywords = conditions["subject_or_body_contains"]
            subject_match = self.check_text_contains(email_data["subject"], keywords)
            body_match = self.check_text_contains(email_data["body"], keywords)
            
            if subject_match:
                return True, f"Subject contains arrival notice keywords: {keywords}"
            elif body_match:
                return True, f"Body contains arrival notice keywords: {keywords}"
            return False, ""
        
        # Rule 1: Default rule
        if conditions.get("default", False):
            return True, "No specific rules matched, applying default routing"
        
        return False, ""
    
    def route_email(self, eml_content: str) -> Dict:
        """Main routing function"""
        try:
            email_data = self.parse_eml_file(eml_content)
            if not email_data:
                raise Exception("Failed to parse email")
            
            for rule in self.routing_rules:
                matched, reason = self.apply_routing_rule(email_data, rule)
                if matched:
                    routing_result = {
                        "routing_queue": rule["queue"].value,
                        "rule_matched": rule["rule_id"],
                        "rule_description": rule["description"],
                        "scenario": rule["scenario"],
                        "action": rule["action"],
                        "priority": rule["priority"],
                        "sla": rule["sla"],
                        "match_reason": reason,
                        "email_data": email_data,
                        "routing_timestamp": datetime.now().isoformat(),
                        "confidence": "HIGH" if rule["rule_id"] != 1 else "DEFAULT"
                    }
                    
                    self.routing_stats["total_processed"] += 1
                    self.routing_stats["rules_matched"][rule["queue"].value] += 1
                    
                    return routing_result
            
            raise Exception("No routing rule matched")
            
        except Exception as e:
            st.error(f"Routing error: {str(e)}")
            return {}

def extract_financial_data(email_body: str) -> Dict:
    """Extract financial information from email"""
    financial_data = {
        "amounts": [],
        "currencies": [],
        "percentages": [],
        "totals": [],
        "budget_items": []
    }
    
    # Money pattern ($123, $1,234.56)
    money_pattern = r'\$[\d,]+\.?\d*'
    amounts = re.findall(money_pattern, email_body)
    financial_data["amounts"] = amounts
    
    # Percentage pattern (25%, 3.5%)
    percentage_pattern = r'\d+\.?\d*%'
    percentages = re.findall(percentage_pattern, email_body)
    financial_data["percentages"] = percentages
    
    # Budget line items
    budget_pattern = r'([A-Za-z\s]+):\s*\$[\d,]+\.?\d*'
    budget_items = re.findall(budget_pattern, email_body)
    financial_data["budget_items"] = budget_items
    
    return financial_data

def extract_entities(email_content: str) -> Dict:
    """Extract key entities from email"""
    entities = {
        "emails": [],
        "phones": [],
        "dates": [],
        "companies": [],
        "amounts": [],
        "account_numbers": [],
        "container_numbers": [],
        "booking_refs": []
    }
    
    # Email pattern
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    entities["emails"] = re.findall(email_pattern, email_content)
    
    # Phone pattern
    phone_pattern = r'\+?1?[-.\s]?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}'
    entities["phones"] = re.findall(phone_pattern, email_content)
    
    # Date pattern
    date_pattern = r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}\b'
    entities["dates"] = re.findall(date_pattern, email_content, re.IGNORECASE)
    
    # Amount pattern
    amount_pattern = r'\$[\d,]+\.?\d*'
    entities["amounts"] = re.findall(amount_pattern, email_content)
    
    # Account number pattern
    account_pattern = r'(?:Account|ID|Customer)\s*[#:]?\s*([A-Z0-9-]+)'
    entities["account_numbers"] = re.findall(account_pattern, email_content, re.IGNORECASE)
    
    # Container number pattern
    container_pattern = r'\b[A-Z]{4}\s?\d{6,7}\s?\d\b'
    entities["container_numbers"] = re.findall(container_pattern, email_content)
    
    # Booking reference pattern
    booking_pattern = r'(?:Booking|B/L|BL)\s*[#:]?\s*([A-Z0-9]+)'
    entities["booking_refs"] = re.findall(booking_pattern, email_content, re.IGNORECASE)
    
    return entities

def analyze_sentiment(email_content: str) -> Dict:
    """Enhanced sentiment analysis"""
    positive_words = ['thanks', 'appreciate', 'excellent', 'great', 'pleased', 'happy', 'satisfied', 'good', 'wonderful']
    negative_words = ['urgent', 'frustrated', 'angry', 'disappointed', 'unacceptable', 'complaint', 'issue', 'problem', 'error', 'wrong', 'terrible', 'awful']
    urgency_words = ['urgent', 'asap', 'immediately', 'critical', 'emergency', 'deadline', 'overdue']
    
    content_lower = email_content.lower()
    
    positive_count = sum(1 for word in positive_words if word in content_lower)
    negative_count = sum(1 for word in negative_words if word in content_lower)
    urgency_count = sum(1 for word in urgency_words if word in content_lower)
    
    # Determine sentiment
    if negative_count > positive_count:
        sentiment = "Negative"
        score = -1
    elif positive_count > negative_count:
        sentiment = "Positive"
        score = 1
    else:
        sentiment = "Neutral"
        score = 0
    
    # Determine urgency
    if urgency_count >= 2:
        urgency = "Critical"
    elif urgency_count == 1:
        urgency = "High"
    else:
        urgency = "Normal"
    
    return {
        "sentiment": sentiment,
        "score": score,
        "urgency": urgency,
        "positive_indicators": positive_count,
        "negative_indicators": negative_count,
        "urgency_indicators": urgency_count
    }

def claude_analysis(email_content: str, api_key: str) -> str:
    """Analyze email with Claude AI"""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        
        prompt = f"""Analyze this email comprehensively and provide actionable insights:

1. **BUSINESS SCENARIO CLASSIFICATION:**
   - What type of business scenario is this?
   - What industry/domain does it relate to?

2. **PRIORITY & URGENCY ASSESSMENT:**
   - Priority level (Critical/High/Medium/Low)
   - Required response time
   - Business impact assessment

3. **KEY INFORMATION EXTRACTION:**
   - Important dates and deadlines
   - Financial information (amounts, budgets, costs)
   - Key stakeholders and contacts
   - Account/reference numbers

4. **RECOMMENDED ACTIONS:**
   - Immediate actions required
   - Follow-up tasks needed
   - Who should be notified
   - Timeline for completion

5. **RISK ASSESSMENT:**
   - Potential risks or concerns
   - Compliance considerations
   - Customer satisfaction impact

6. **NEXT STEPS:**
   - Specific actionable steps
   - Resource requirements
   - Success criteria

Email content:
{email_content}

Provide a structured, actionable analysis that a business user can immediately act upon."""
        
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return message.content[0].text
        
    except Exception as e:
        return f"❌ **Error in analysis:** {str(e)}\n\n**Possible solutions:**\n- Check your API key format (should start with 'sk-ant-')\n- Verify your API key is active\n- Ensure you have API credits available"

def get_api_key():
    """Get API key from environment or user input"""
    # Check environment variable first
    env_key = os.getenv('ANTHROPIC_API_KEY')
    if env_key and env_key != "skooooo":  # Ignore placeholder
        return env_key
    
    # Get from sidebar
    api_key = st.sidebar.text_input(
        "Claude API Key", 
        type="password", 
        help="Enter your Anthropic Claude API key (starts with sk-ant-)",
        placeholder="sk-ant-..."
    )
    
    return api_key

def main():
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>📧 Brokerage Email Automation Manager</h1>
        <h2 style="text-align: center; color: white; margin: 0; font-size: 1.5em;">BEAM</h2>
        <p style="text-align: center; color: white; margin: 0;">
            Intelligent Email Processing & AI-Powered Analysis
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar
    st.sidebar.header("🔧 Configuration")
    
    # API Key handling
    api_key = get_api_key()
    
    if api_key:
        if api_key.startswith('sk-ant-'):
            st.sidebar.success("✅ Valid API key format")
        else:
            st.sidebar.error("❌ API key should start with 'sk-ant-'")
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📁 Supported File Types")
    st.sidebar.markdown("""
    **📧 .eml files** - Standard email format (Recommended)
    
    **📮 .msg files** - Outlook email format (Basic support)
    
    💡 **Tip:** For best results with .msg files, save as .eml in Outlook first
    """)
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📋 Routing Rules")
    st.sidebar.markdown("""
    **Rule 1:** Default → Shipment_Initiation_Brkg_Inland_SI *(24h SLA)*
    
    **Rule 2:** Account Inquiry → Account_Inquiry_US *(4h SLA)*
    
    **Rule 3:** Evergreen Line → ORD_SI-Non_UPS_Shipments *(8h SLA)*
    
    **Rule 4:** RAFT Pre-Alert → RAFT_PreAlert *(2h SLA)*
    
    **Rule 5:** RAFT Arrival → RAFT_ArrivalNotice *(1h SLA)*
    """)
    
    # Initialize routing agent
    if 'routing_agent' not in st.session_state:
        st.session_state.routing_agent = EmailRoutingAgent()
    
    agent = st.session_state.routing_agent
    
    # Main interface
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("📁 Email Upload & Processing")
        
        # File upload
        uploaded_file = st.file_uploader(
            "Upload email file (.eml or .msg)",
            type=['eml', 'msg'],
            help="Upload an email file in .eml or .msg format for processing"
        )
        
        if uploaded_file is not None:
            # Read file content
            try:
                if uploaded_file.name.endswith('.msg'):
                    # For .msg files, try to read as text (may require conversion)
                    eml_content = uploaded_file.read().decode('utf-8', errors='ignore')
                    st.info("📧 .msg file detected - processing as email format")
                else:
                    # For .eml files, standard processing
                    eml_content = uploaded_file.read().decode('utf-8')
                    
            except Exception as e:
                st.error(f"Error reading file: {str(e)}")
                st.info("💡 Tip: If using .msg files, try saving as .eml format in Outlook first")
                return
            
            # Process email
            with st.spinner("🔄 Processing email..."):
                routing_result = agent.route_email(eml_content)
            
            if routing_result:
                email_data = routing_result['email_data']
                
                # Display routing result with clear scenario
                st.markdown(f"""
                <div class="routing-result">
                    <h3>🎯 ROUTING DECISION</h3>
                    <p><strong>📋 SCENARIO:</strong> {routing_result['scenario']}</p>
                    <p><strong>🏷️ QUEUE:</strong> {routing_result['routing_queue']}</p>
                    <p><strong>⚡ PRIORITY:</strong> {routing_result['priority']}</p>
                    <p><strong>⏰ SLA:</strong> {routing_result['sla']}</p>
                    <p><strong>✅ RULE:</strong> Rule {routing_result['rule_matched']} - {routing_result['rule_description']}</p>
                    <p><strong>🔍 MATCH REASON:</strong> {routing_result['match_reason']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                # Action recommendations
                st.markdown(f"""
                <div class="action-box">
                    <h3>🎯 RECOMMENDED ACTION</h3>
                    <p><strong>{routing_result['action']}</strong></p>
                    <p><strong>📅 Response Required By:</strong> {routing_result['sla']} from now</p>
                    <p><strong>🔔 Next Steps:</strong> Assign to {routing_result['routing_queue']} team for processing</p>
                </div>
                """, unsafe_allow_html=True)
                
                # Email details tabs
                tab1, tab2, tab3, tab4 = st.tabs(["📧 Email Details", "📊 Smart Analysis", "  AI Analysis", "📥 Export"])
                
                with tab1:
                    st.subheader("Email Information")
                    
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown(f"**From:** {email_data.get('from', 'N/A')}")
                        st.markdown(f"**To:** {email_data.get('to', 'N/A')}")
                        st.markdown(f"**Subject:** {email_data.get('subject', 'N/A')}")
                        st.markdown(f"**Date:** {email_data.get('date', 'N/A')}")
                    
                    with col_b:
                        st.markdown(f"**Message ID:** {email_data.get('message_id', 'N/A')}")
                        st.markdown(f"**CC:** {email_data.get('cc', 'N/A')}")
                        st.markdown(f"**Priority:** {email_data.get('priority', 'Normal')}")
                        if email_data.get('attachments'):
                            st.markdown(f"**Attachments:** {', '.join(email_data['attachments'])}")
                    
                    st.subheader("Email Body")
                    if email_data.get('is_html'):
                        st.markdown("*HTML content detected - showing cleaned text*")
                    
                    # Show email body in scrollable box
                    body_text = email_data.get('body', '')[:2000]  # Limit display
                    st.text_area("Email Content", body_text, height=300, disabled=True)
                
                with tab2:
                    st.subheader("📊 Smart Analysis")
                    
                    # Entity extraction
                    full_content = email_data.get('body', '') + ' ' + email_data.get('subject', '')
                    entities = extract_entities(full_content)
                    financial_data = extract_financial_data(full_content)
                    
                    # Key metrics
                    col_met1, col_met2, col_met3 = st.columns(3)
                    col_met1.metric("📧 Email Addresses", len(entities['emails']))
                    col_met2.metric("💰 Amounts Found", len(entities['amounts']))
                    col_met3.metric("📅 Dates Found", len(entities['dates']))
                    
                    # Entity details
                    col_x, col_y = st.columns(2)
                    with col_x:
                        if entities['emails']:
                            st.markdown("**📧 Email Addresses:**")
                            for email_addr in entities['emails'][:5]:  # Limit display
                                st.write(f"• {email_addr}")
                        
                        if entities['phones']:
                            st.markdown("**📞 Phone Numbers:**")
                            for phone in entities['phones'][:5]:
                                st.write(f"• {phone}")
                        
                        if entities['account_numbers']:
                            st.markdown("**🔢 Account Numbers:**")
                            for acc in entities['account_numbers'][:5]:
                                st.write(f"• {acc}")
                    
                    with col_y:
                        if entities['dates']:
                            st.markdown("**📅 Important Dates:**")
                            for date in entities['dates'][:5]:
                                st.write(f"• {date}")
                        
                        if entities['amounts']:
                            st.markdown("**💰 Financial Amounts:**")
                            for amount in entities['amounts'][:5]:
                                st.write(f"• {amount}")
                        
                        if entities['container_numbers']:
                            st.markdown("**📦 Container Numbers:**")
                            for container in entities['container_numbers'][:5]:
                                st.write(f"• {container}")
                    
                    # Sentiment analysis
                    sentiment_data = analyze_sentiment(full_content)
                    
                    st.markdown("**😊 Sentiment & Urgency Analysis:**")
                    col_sent1, col_sent2, col_sent3, col_sent4 = st.columns(4)
                    col_sent1.metric("Sentiment", sentiment_data['sentiment'])
                    col_sent2.metric("Urgency Level", sentiment_data['urgency'])
                    col_sent3.metric("Positive Signals", sentiment_data['positive_indicators'])
                    col_sent4.metric("Negative Signals", sentiment_data['negative_indicators'])
                
                with tab3:
                    st.subheader("  Comprehensive Analysis")
                    
                    if not api_key:
                        st.warning("🔑 Please enter API key in sidebar to enable advanced analysis")
                    elif not api_key.startswith('sk-ant-'):
                        st.error("❌ Invalid API key format. API keys should start with 'sk-ant-'")
                    else:
                        with st.spinner("  Analyzing..."):
                            email_content = f"""
                            From: {email_data.get('from', 'N/A')}
                            To: {email_data.get('to', 'N/A')}
                            Subject: {email_data.get('subject', 'N/A')}
                            Date: {email_data.get('date', 'N/A')}
                            Routing Decision: {routing_result['scenario']} → {routing_result['routing_queue']}
                            
                            Body:
                            {email_data.get('body', 'N/A')}
                            """
                            
                            analysis = claude_analysis(email_content, api_key)
                            st.markdown(analysis)
                
                with tab4:
                    st.subheader("📥 Export Results")
                    
                    # Prepare comprehensive export data
                    export_data = {
                        "routing_decision": {
                            "queue": routing_result['routing_queue'],
                            "rule": routing_result['rule_matched'],
                            "scenario": routing_result['scenario'],
                            "action": routing_result['action'],
                            "priority": routing_result['priority'],
                            "sla": routing_result['sla'],
                            "match_reason": routing_result['match_reason']
                        },
                        "email_metadata": {
                            "from": email_data.get('from'),
                            "to": email_data.get('to'),
                            "subject": email_data.get('subject'),
                            "date": email_data.get('date'),
                            "attachments": email_data.get('attachments', [])
                        },
                        "entities": entities,
                        "sentiment": sentiment_data,
                        "financial_data": financial_data,
                        "processing_timestamp": datetime.now().isoformat()
                    }
                    
                    export_json = json.dumps(export_data, indent=2)
                    
                    st.download_button(
                        label="📋 Download Complete Analysis (JSON)",
                        data=export_json,
                        file_name=f"email_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json"
                    )
                    
                    # CSV export for entities
                    if any(entities.values()):
                        rows = []
                        for entity_type, entity_list in entities.items():
                            for entity in entity_list:
                                rows.append({"Type": entity_type, "Value": entity})
                        
                        if rows:
                            entity_df = pd.DataFrame(rows)
                            csv = entity_df.to_csv(index=False)
                            st.download_button(
                                label="📊 Download Entities (CSV)",
                                data=csv,
                                file_name=f"email_entities_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )
    
    with col2:
        st.header("📊 System Dashboard")
        
        # Routing statistics
        stats = agent.routing_stats
        
        st.metric("Total Processed", stats['total_processed'])
        
        if stats['total_processed'] > 0:
            st.subheader("Queue Distribution")
            
            # Create pie chart
            queue_data = {k: v for k, v in stats['rules_matched'].items() if v > 0}
            
            if queue_data:
                fig = px.pie(
                    values=list(queue_data.values()),
                    names=list(queue_data.keys()),
                    title="Email Routing Distribution",
                    color_discrete_sequence=px.colors.qualitative.Set3
                )
                st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("---")
        st.subheader("🔧 System Configuration")
        st.markdown(f"**Team Mailbox:** {agent.team_mailbox}")
        st.markdown(f"**Distribution List:** {agent.distribution_list}")
        st.markdown(f"**Rules Active:** {len(agent.routing_rules)}")
        
        # Rule summary
        st.markdown("---")
        st.subheader("📋 Rule Summary")
        for rule in agent.routing_rules:
            st.markdown(f"""
            <div class="rule-box">
                <strong>Rule {rule['rule_id']}:</strong> {rule['scenario']}<br>
                <strong>Priority:</strong> {rule['priority']} | <strong>SLA:</strong> {rule['sla']}
            </div>
            """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()

