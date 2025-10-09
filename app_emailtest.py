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
from io import BytesIO

# Page config
st.set_page_config(
    page_title="UPS Email Processing System",
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
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #4caf50;
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
                "conditions": {
                    "subject_contains": ["power of attorney", "poa", "account needed", "account setup"],
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
        """Parse .eml file content"""
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
            st.error(f"Error parsing email: {str(e)}")
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
    
    def apply_routing_rule(self, email_data: Dict, rule: Dict) -> bool:
        """Apply specific routing rule"""
        conditions = rule["conditions"]
        
        # Rule 2: Account Inquiry
        if "subject_contains" in conditions and rule["rule_id"] == 2:
            subject_match = self.check_text_contains(email_data["subject"], conditions["subject_contains"])
            attachment_match = False
            
            if conditions.get("check_attachments", False):
                attachment_match = self.check_attachment_naming(
                    email_data["attachments"], conditions["subject_contains"]
                )
            
            return subject_match or attachment_match
        
        # Rule 3: Domain-based routing
        if "from_domain" in conditions:
            from_domain = self.extract_from_domain(email_data["from"])
            return from_domain == conditions["from_domain"]
        
        # Rule 4: RAFT Pre-Alert
        if "subject_contains" in conditions and rule["rule_id"] == 4:
            return self.check_text_contains(email_data["subject"], conditions["subject_contains"])
        
        # Rule 5: RAFT Arrival Notice
        if "subject_or_body_contains" in conditions:
            keywords = conditions["subject_or_body_contains"]
            subject_match = self.check_text_contains(email_data["subject"], keywords)
            body_match = self.check_text_contains(email_data["body"], keywords)
            return subject_match or body_match
        
        # Rule 1: Default rule
        if conditions.get("default", False):
            return True
        
        return False
    
    def route_email(self, eml_content: str) -> Dict:
        """Main routing function"""
        try:
            email_data = self.parse_eml_file(eml_content)
            if not email_data:
                raise Exception("Failed to parse email")
            
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
        "totals": []
    }
    
    # Money pattern ($123, $1,234.56)
    money_pattern = r'\$[\d,]+\.?\d*'
    amounts = re.findall(money_pattern, email_body)
    financial_data["amounts"] = amounts
    
    # Percentage pattern (25%, 3.5%)
    percentage_pattern = r'\d+\.?\d*%'
    percentages = re.findall(percentage_pattern, email_body)
    financial_data["percentages"] = percentages
    
    return financial_data

def extract_entities(email_content: str) -> Dict:
    """Extract key entities from email"""
    entities = {
        "emails": [],
        "phones": [],
        "dates": [],
        "companies": [],
        "amounts": []
    }
    
    # Email pattern
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    entities["emails"] = re.findall(email_pattern, email_content)
    
    # Phone pattern
    phone_pattern = r'\+?1?[-.\s]?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}'
    entities["phones"] = re.findall(phone_pattern, email_content)
    
    # Date pattern (simple)
    date_pattern = r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}\b'
    entities["dates"] = re.findall(date_pattern, email_content, re.IGNORECASE)
    
    # Amount pattern
    amount_pattern = r'\$[\d,]+\.?\d*'
    entities["amounts"] = re.findall(amount_pattern, email_content)
    
    return entities

def analyze_sentiment(email_content: str) -> Dict:
    """Simple sentiment analysis"""
    positive_words = ['thanks', 'appreciate', 'excellent', 'great', 'pleased', 'happy', 'satisfied']
    negative_words = ['urgent', 'frustrated', 'angry', 'disappointed', 'unacceptable', 'complaint', 'issue', 'problem']
    
    content_lower = email_content.lower()
    
    positive_count = sum(1 for word in positive_words if word in content_lower)
    negative_count = sum(1 for word in negative_words if word in content_lower)
    
    if negative_count > positive_count:
        sentiment = "Negative"
        score = -1
    elif positive_count > negative_count:
        sentiment = "Positive"
        score = 1
    else:
        sentiment = "Neutral"
        score = 0
    
    return {
        "sentiment": sentiment,
        "score": score,
        "positive_indicators": positive_count,
        "negative_indicators": negative_count
    }

def claude_analysis(email_content: str, api_key: str) -> str:
    """Analyze email with Claude AI"""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        
        prompt = f"""Analyze this email and provide:
1. Email type classification
2. Sentiment analysis (positive/negative/neutral)
3. Urgency level (low/medium/high/critical)
4. Key information summary
5. Recommended actions
6. Business impact assessment

Email content:
{email_content}

Provide a structured analysis in markdown format."""
        
        message = client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=1500,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return message.content[0].text
        
    except Exception as e:
        return f"Error in Claude analysis: {str(e)}"

def create_download_link(content: str, filename: str, text: str) -> str:
    """Create download link for content"""
    b64 = base64.b64encode(content.encode()).decode()
    href = f'<a href="data:text/plain;base64,{b64}" download="{filename}">{text}</a>'
    return href

def main():
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>📧 UPS Email Processing & Routing System</h1>
        <p style="text-align: center; color: white; margin: 0;">
            ORD & SF Email to Case - Automated Processing & Claude AI Analysis
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar
    st.sidebar.header("🔧 Configuration")
    api_key = st.sidebar.text_input("Claude API Key", type="password", help="Enter your Anthropic Claude API key for AI analysis")
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📋 Routing Rules")
    st.sidebar.markdown("""
    **Rule 1:** Default → Shipment_Initiation_Brkg_Inland_SI
    
    **Rule 2:** Account Inquiry → Account_Inquiry_US
    
    **Rule 3:** Evergreen Line → ORD_SI-Non_UPS_Shipments
    
    **Rule 4:** RAFT Pre-Alert → RAFT_PreAlert
    
    **Rule 5:** RAFT Arrival → RAFT_ArrivalNotice
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
            "Upload .eml file",
            type=['eml'],
            help="Upload an email file in .eml format for processing"
        )
        
        if uploaded_file is not None:
            # Read file content
            eml_content = uploaded_file.read().decode('utf-8')
            
            # Process email
            with st.spinner("🔄 Processing email..."):
                routing_result = agent.route_email(eml_content)
            
            if routing_result:
                email_data = routing_result['email_data']
                
                # Display routing result
                st.markdown(f"""
                <div class="routing-result">
                    <h3>🎯 Routing Decision</h3>
                    <p><strong>Queue:</strong> {routing_result['routing_queue']}</p>
                    <p><strong>Rule:</strong> {routing_result['rule_matched']} - {routing_result['rule_description']}</p>
                    <p><strong>Confidence:</strong> {routing_result['confidence']}</p>
                    <p><strong>Processed:</strong> {routing_result['routing_timestamp']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                # Email details tabs
                tab1, tab2, tab3, tab4 = st.tabs(["📧 Email Details", "📊 Analysis", "🤖 AI Analysis", "📥 Export"])
                
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
                        st.markdown("*HTML content detected*")
                        with st.expander("View Raw HTML"):
                            st.code(email_data.get('body', ''), language='html')
                    else:
                        st.text_area("Email Content", email_data.get('body', ''), height=300)
                
                with tab2:
                    st.subheader("📊 Automated Analysis")
                    
                    # Entity extraction
                    entities = extract_entities(email_data.get('body', '') + ' ' + email_data.get('subject', ''))
                    
                    col_x, col_y = st.columns(2)
                    with col_x:
                        st.markdown("**📧 Email Addresses Found:**")
                        for email_addr in entities['emails']:
                            st.write(f"• {email_addr}")
                        
                        st.markdown("**📞 Phone Numbers Found:**")
                        for phone in entities['phones']:
                            st.write(f"• {phone}")
                    
                    with col_y:
                        st.markdown("**📅 Dates Found:**")
                        for date in entities['dates']:
                            st.write(f"• {date}")
                        
                        st.markdown("**💰 Amounts Found:**")
                        for amount in entities['amounts']:
                            st.write(f"• {amount}")
                    
                    # Sentiment analysis
                    sentiment_data = analyze_sentiment(email_data.get('body', '') + ' ' + email_data.get('subject', ''))
                    
                    st.markdown("**😊 Sentiment Analysis:**")
                    col_sent1, col_sent2, col_sent3 = st.columns(3)
                    col_sent1.metric("Sentiment", sentiment_data['sentiment'])
                    col_sent2.metric("Positive Indicators", sentiment_data['positive_indicators'])
                    col_sent3.metric("Negative Indicators", sentiment_data['negative_indicators'])
                
                with tab3:
                    st.subheader("🤖 Claude AI Analysis")
                    
                    # FIXED BUTTON LOGIC - No more syntax errors!
                    if st.button("🚀 Analyze with Claude AI", type="primary"):
                        if not api_key:
                            st.warning("🔑 Please enter Claude API key in sidebar")
                        elif not email_data.get('body'):
                            st.warning("📧 No email content to analyze")
                        else:
                            with st.spinner("🧠 Analyzing with Claude AI..."):
                                try:
                                    email_content = f"""
                                    From: {email_data.get('from', 'N/A')}
                                    To: {email_data.get('to', 'N/A')}
                                    Subject: {email_data.get('subject', 'N/A')}
                                    Date: {email_data.get('date', 'N/A')}
                                    
                                    Body:
                                    {email_data.get('body', 'N/A')}
                                    """
                                    
                                    analysis = claude_analysis(email_content, api_key)
                                    st.success("✅ Claude AI Analysis Complete!")
                                    st.markdown("### 🤖 AI Analysis Results")
                                    st.markdown(analysis)
                                    
                                    # Store analysis in session state for export
                                    if 'claude_analysis' not in st.session_state:
                                        st.session_state.claude_analysis = {}
                                    st.session_state.claude_analysis[uploaded_file.name] = analysis
                                    
                                except Exception as e:
                                    st.error(f"❌ Error with Claude AI analysis: {str(e)}")
                                    st.info("💡 Please check your API key and try again")
                    
                    # Alternative: Show analysis from session state if exists
                    if 'claude_analysis' in st.session_state and uploaded_file and uploaded_file.name in st.session_state.claude_analysis:
                        st.markdown("### 🤖 Previous AI Analysis")
                        with st.expander("View Previous Analysis", expanded=False):
                            st.markdown(st.session_state.claude_analysis[uploaded_file.name])
                
                with tab4:
                    st.subheader("📥 Export Results")
                    
                    # Prepare export data
                    export_data = {
                        "routing_result": routing_result,
                        "entities": entities,
                        "sentiment": sentiment_data,
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    export_json = json.dumps(export_data, indent=2)
                    
                    st.download_button(
                        label="📋 Download Analysis as JSON",
                        data=export_json,
                        file_name=f"email_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json"
                    )
                    
                    # CSV export for entities
                    if entities['emails'] or entities['phones'] or entities['amounts']:
                        entity_df = pd.DataFrame({
                            'Type': ['Email'] * len(entities['emails']) + 
                                   ['Phone'] * len(entities['phones']) + 
                                   ['Amount'] * len(entities['amounts']),
                            'Value': entities['emails'] + entities['phones'] + entities['amounts']
                        })
                        
                        csv = entity_df.to_csv(index=False)
                        st.download_button(
                            label="📊 Download Entities as CSV",
                            data=csv,
                            file_name=f"email_entities_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )
    
    with col2:
        st.header("📊 Statistics")
        
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
                    title="Email Routing Distribution"
                )
                st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("---")
        st.subheader("🔧 System Info")
        st.markdown(f"**Team Mailbox:** {agent.team_mailbox}")
        st.markdown(f"**Distribution List:** {agent.distribution_list}")
        st.markdown(f"**Rules Configured:** {len(agent.routing_rules)}")
        
        # Quick test section
        st.markdown("---")
        st.subheader("🧪 Quick Test")
        
        if st.button("Test Sample Emails"):
            st.info("Feature coming soon - test with predefined email samples")

if __name__ == "__main__":
    main()
