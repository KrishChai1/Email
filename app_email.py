import streamlit as st
import anthropic
import json
from datetime import datetime
import re
from typing import Dict, List, Tuple, Optional
import pandas as pd
from docx import Document
import PyPDF2
from PIL import Image
import io
import email
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
from email.utils import formatdate
import base64

# Try to import MSG support (optional)
try:
    import extract_msg
    MSG_SUPPORT = True
except ImportError:
    MSG_SUPPORT = False
    st.warning("⚠️ For .msg file support, install: pip install extract-msg")

# Configure Streamlit page
st.set_page_config(
    page_title="ORD Shipment Routing Agent",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Add custom CSS for better UI
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #1f4e79, #2e8b57);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
    }
    .routing-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #1f4e79;
        margin: 1rem 0;
    }
    .confidence-high { border-left-color: #28a745; }
    .confidence-medium { border-left-color: #ffc107; }
    .confidence-low { border-left-color: #dc3545; }
    .sample-box {
        background: #e3f2fd;
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #2196f3;
        margin: 1rem 0;
    }
    .forwarding-simulation {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 1rem;
        border-radius: 10px;
        border: 2px solid #007bff;
        margin: 1rem 0;
    }
    .email-preview {
        background: #2d3748;
        color: #e2e8f0;
        padding: 1rem;
        border-radius: 8px;
        font-family: 'Courier New', monospace;
        border-left: 4px solid #4299e1;
    }
</style>
""", unsafe_allow_html=True)

class ShipmentRoutingAgent:
    def __init__(self, api_key: str):
        """Initialize the routing agent with Claude API"""
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else None
        self.routing_rules = self._load_routing_rules()
        
    def _load_routing_rules(self) -> Dict:
        """Load the routing rules based on the ORD shipment initiation document"""
        return {
            "team_mailbox": "noreply-ordchbdocdesk@ups.com",
            "distribution_list": "ordchbdocdesk@ups.com",
            
            "routing_queues": {
                "Account_Inquiry_US": {
                    "description": "POA, Account Setup, Account Needed requests",
                    "keywords": ["Power of Attorney", "POA", "Account Needed", "Account Setup"],
                    "priority": 1,
                    "color": "#dc3545",
                    "team": "Customer Account Services Team",
                    "contacts": [
                        "account.setup@ups.com",
                        "customer.onboarding@ups.com",
                        "legal.compliance@ups.com"
                    ],
                    "sla": "4 hours",
                    "escalation": "account.manager@ups.com"
                },
                "ORD_SI-Non_UPS_Shipments": {
                    "description": "Emails from Evergreen Line domain",
                    "from_domain": "@mail.evergreen-line.com",
                    "priority": 2,
                    "color": "#fd7e14",
                    "team": "External Carrier Relations Team",
                    "contacts": [
                        "carrier.relations@ups.com",
                        "evergreen.coordinator@ups.com"
                    ],
                    "sla": "2 hours",
                    "escalation": "carrier.manager@ups.com"
                },
                "ORD_Pre-Alert_SI": {
                    "description": "Pre-Alert notifications",
                    "subject_keywords": ["Pre-Alert", "Pre Alert", "PreAlert"],
                    "priority": 3,
                    "color": "#ffc107",
                    "team": "Shipment Coordination Team",
                    "contacts": [
                        "prealert.team@ups.com",
                        "shipment.coordination@ups.com"
                    ],
                    "sla": "1 hour",
                    "escalation": "operations.supervisor@ups.com"
                },
                "ORD_Ocean_Arrival_Notices": {
                    "description": "Ocean arrival notices",
                    "content_keywords": ["Arrival Notice"],
                    "priority": 4,
                    "color": "#28a745",
                    "team": "Port Operations Team",
                    "contacts": [
                        "port.operations@ups.com",
                        "arrival.notices@ups.com",
                        "customs.clearance@ups.com"
                    ],
                    "sla": "30 minutes",
                    "escalation": "port.supervisor@ups.com"
                },
                "Shipment_Initiation_Brkg_Inland_SI": {
                    "description": "Default queue for other shipment initiations",
                    "priority": 5,
                    "color": "#6c757d",
                    "team": "General Shipment Processing Team",
                    "contacts": [
                        "shipment.processing@ups.com",
                        "inland.transport@ups.com"
                    ],
                    "sla": "6 hours",
                    "escalation": "processing.manager@ups.com"
                }
            }
        }
    
    def extract_text_from_file(self, file, file_type: str) -> str:
        """Extract text from various file types including .eml and .msg"""
        try:
            if file_type == "docx":
                doc = Document(file)
                text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
                return text
            
            elif file_type == "pdf":
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text()
                return text
            
            elif file_type == "eml":
                # Handle .eml email files
                content = file.read().decode('utf-8', errors='ignore')
                msg = email.message_from_string(content)
                
                # Extract email components
                email_text = f"From: {msg.get('From', '')}\n"
                email_text += f"To: {msg.get('To', '')}\n"
                email_text += f"Subject: {msg.get('Subject', '')}\n"
                email_text += f"Date: {msg.get('Date', '')}\n\n"
                
                # Extract body
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            email_text += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                            break
                else:
                    email_text += msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                
                return email_text
            
            elif file_type == "msg":
                # Handle .msg Outlook files
                if not MSG_SUPPORT:
                    st.error("❌ .msg file support not available. Install extract-msg package.")
                    return ""
                
                try:
                    # Save uploaded file temporarily
                    with open("temp.msg", "wb") as f:
                        f.write(file.read())
                    
                    # Extract message
                    msg = extract_msg.Message("temp.msg")
                    
                    email_text = f"From: {msg.sender}\n"
                    email_text += f"To: {msg.to}\n"
                    email_text += f"Subject: {msg.subject}\n"
                    email_text += f"Date: {msg.date}\n\n"
                    email_text += msg.body or ""
                    
                    # Clean up temp file
                    import os
                    os.remove("temp.msg")
                    
                    return email_text
                    
                except Exception as e:
                    st.error(f"Error processing .msg file: {str(e)}")
                    return ""
            
            elif file_type == "txt":
                return file.read().decode('utf-8')
            
            elif file_type in ["jpg", "jpeg", "png", "bmp", "tiff"]:
                st.warning("⚠️ Image uploaded. Please manually extract text and paste below.")
                return "Image file uploaded - please extract text manually"
            
            else:
                return file.read().decode('utf-8', errors='ignore')
                
        except Exception as e:
            st.error(f"Error extracting text: {str(e)}")
            return ""
    
    def parse_email_content(self, content: str) -> Dict:
        """Parse email content to extract headers and body"""
        try:
            # Try to parse as email message
            msg = email.message_from_string(content)
            
            return {
                "from": msg.get("From", ""),
                "to": msg.get("To", ""),
                "subject": msg.get("Subject", ""),
                "body": self._get_email_body(msg),
                "headers": dict(msg.items())
            }
        except:
            # If not proper email format, extract from text
            lines = content.split('\n')
            subject_line = ""
            body = content
            from_addr = ""
            
            for line in lines[:10]:
                if line.lower().startswith(('subject:', 'subj:')):
                    subject_line = line.split(':', 1)[1].strip()
                elif line.lower().startswith('from:'):
                    from_addr = line.split(':', 1)[1].strip()
            
            return {
                "from": from_addr,
                "to": "",
                "subject": subject_line,
                "body": body,
                "headers": {}
            }
    
    def _get_email_body(self, msg) -> str:
        """Extract body from email message"""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode('utf-8', errors='ignore')
        else:
            return msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        return ""
    
    def determine_routing(self, content: str, filename: str = "") -> Tuple[str, str, float, List[str]]:
        """Determine routing based on content analysis and rules"""
        
        email_data = self.parse_email_content(content)
        reasons = []
        
        # Check each routing rule in priority order
        sorted_queues = sorted(
            self.routing_rules["routing_queues"].items(),
            key=lambda x: x[1]["priority"]
        )
        
        for queue_name, rule in sorted_queues:
            if queue_name == "Shipment_Initiation_Brkg_Inland_SI":
                continue
            
            # Check Account_Inquiry_US rules
            if queue_name == "Account_Inquiry_US":
                keywords = rule.get("keywords", [])
                subject = email_data.get("subject", "").lower()
                body = email_data.get("body", "").lower()
                filename_lower = filename.lower()
                
                matched_keywords = []
                for keyword in keywords:
                    if (keyword.lower() in subject or 
                        keyword.lower() in body or 
                        keyword.lower() in filename_lower):
                        matched_keywords.append(keyword)
                
                if matched_keywords:
                    confidence = min(0.95, 0.4 + 0.2 * len(matched_keywords))
                    reasons.append(f"Matched keywords: {', '.join(matched_keywords)}")
                    return queue_name, rule["description"], confidence, reasons
            
            # Check ORD_SI-Non_UPS_Shipments rules
            elif queue_name == "ORD_SI-Non_UPS_Shipments":
                from_domain = rule.get("from_domain", "")
                sender = email_data.get("from", "").lower()
                
                if from_domain.lower() in sender:
                    reasons.append(f"Email from domain: {from_domain}")
                    return queue_name, rule["description"], 0.95, reasons
            
            # Check ORD_Pre-Alert_SI rules
            elif queue_name == "ORD_Pre-Alert_SI":
                keywords = rule.get("subject_keywords", [])
                subject = email_data.get("subject", "").lower()
                
                for keyword in keywords:
                    if keyword.lower() in subject:
                        reasons.append(f"Subject contains: {keyword}")
                        return queue_name, rule["description"], 0.90, reasons
            
            # Check ORD_Ocean_Arrival_Notices rules
            elif queue_name == "ORD_Ocean_Arrival_Notices":
                keywords = rule.get("content_keywords", [])
                subject = email_data.get("subject", "").lower()
                body = email_data.get("body", "").lower()
                
                for keyword in keywords:
                    if keyword.lower() in subject or keyword.lower() in body:
                        location = "subject" if keyword.lower() in subject else "body"
                        reasons.append(f"Found '{keyword}' in {location}")
                        return queue_name, rule["description"], 0.85, reasons
        
        # Default to catch-all queue
        reasons.append("No specific routing rules matched - using default queue")
        return "Shipment_Initiation_Brkg_Inland_SI", self.routing_rules["routing_queues"]["Shipment_Initiation_Brkg_Inland_SI"]["description"], 0.70, reasons
    
    def analyze_with_claude(self, content: str, filename: str = "") -> Dict:
        """Use Claude API for advanced content analysis"""
        
        if not self.client:
            return {
                "document_type": "unknown",
                "key_entities": [],
                "urgency_level": 3,
                "recommended_queue": "Shipment_Initiation_Brkg_Inland_SI",
                "confidence_score": 0.5,
                "reasons": ["Claude API key not provided"]
            }
        
        prompt = f"""
        Analyze this document/email content for UPS ORD (Chicago) shipment routing:
        
        Filename: {filename}
        Content: {content[:2000]}...
        
        Determine:
        1. Document type (email, shipment document, invoice, etc.)
        2. Key entities (shipper, consignee, shipment details)
        3. Urgency level (1-5, where 5 is most urgent)
        4. Recommended routing queue
        5. Confidence score (0-1)
        6. Key reasons for routing decision
        
        Routing options:
        - Account_Inquiry_US: For POA, Account Setup requests
        - ORD_SI-Non_UPS_Shipments: For Evergreen Line emails
        - ORD_Pre-Alert_SI: For Pre-Alert notifications  
        - ORD_Ocean_Arrival_Notices: For Arrival Notices
        - Shipment_Initiation_Brkg_Inland_SI: Default for other shipment initiations
        
        Respond in JSON format with exact field names: document_type, key_entities, urgency_level, recommended_queue, confidence_score, reasons
        """
        
        try:
            response = self.client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            claude_analysis = json.loads(response.content[0].text)
            return claude_analysis
            
        except Exception as e:
            st.error(f"Claude API error: {str(e)}")
            return {
                "document_type": "unknown",
                "key_entities": [],
                "urgency_level": 3,
                "recommended_queue": "Shipment_Initiation_Brkg_Inland_SI",
                "confidence_score": 0.5,
                "reasons": [f"API error: {str(e)}"]
            }

def display_routing_result(queue_name: str, description: str, confidence: float, reasons: List[str], rules: Dict):
    """Display routing result with styled card and destination details"""
    queue_info = rules["routing_queues"].get(queue_name, {})
    color = queue_info.get("color", "#6c757d")
    
    confidence_class = "confidence-high" if confidence > 0.8 else "confidence-medium" if confidence > 0.5 else "confidence-low"
    
    st.markdown(f"""
    <div class="routing-card {confidence_class}">
        <h4 style="color: {color}; margin: 0;">📍 {queue_name}</h4>
        <p style="margin: 0.5rem 0;"><strong>Description:</strong> {description}</p>
        <p style="margin: 0.5rem 0;"><strong>Confidence:</strong> {confidence:.1%}</p>
        <p style="margin: 0;"><strong>Team:</strong> {queue_info.get('team', 'Unknown Team')}</p>
    </div>
    """, unsafe_allow_html=True)
    
    if reasons:
        st.markdown("**🔍 Routing Reasons:**")
        for reason in reasons:
            st.write(f"• {reason}")

def simulate_email_forwarding(queue_name: str, original_email: Dict, rules: Dict):
    """Simulate where the email would be forwarded after routing"""
    queue_info = rules["routing_queues"].get(queue_name, {})
    
    st.markdown("""
    <div class="forwarding-simulation">
        <h3 style="color: #007bff; margin-top: 0;">📧 Email Forwarding Simulation</h3>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("#### 📥 **Incoming Email**")
        st.info(f"""
        **From:** {original_email.get('from', 'Unknown')}
        **To:** {rules['team_mailbox']}
        **Subject:** {original_email.get('subject', 'No subject')}
        **Received:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """)
    
    with col2:
        st.markdown("#### 📤 **Routed To Team**")
        
        contacts = queue_info.get('contacts', [])
        team = queue_info.get('team', 'Unknown Team')
        sla = queue_info.get('sla', 'N/A')
        escalation = queue_info.get('escalation', 'N/A')
        
        # Primary contacts
        st.success(f"""
        **Team:** {team}
        **Queue:** {queue_name}
        **SLA Target:** {sla}
        """)
        
        st.markdown("**📬 Recipients:**")
        for i, contact in enumerate(contacts):
            priority = "Primary" if i == 0 else "CC"
            st.write(f"• **{priority}:** {contact}")
        
        if escalation != 'N/A':
            st.write(f"• **Escalation:** {escalation}")
    
    # Show the forwarded email preview
    st.markdown("#### 📋 **Forwarded Email Preview**")
    
    forwarded_subject = f"[{queue_name}] {original_email.get('subject', 'No subject')}"
    
    # Determine priority based on queue
    priority_level = "High" if queue_info.get('priority', 5) <= 2 else "Normal"
    priority_color = "🔴" if priority_level == "High" else "🟢"
    
    forwarded_body = f"""--- AUTO-ROUTED EMAIL ---
Original From: {original_email.get('from', 'Unknown')}
Original To: {rules['team_mailbox']}
Routing Decision: {queue_name}
Assigned Team: {team}
Priority Level: {priority_color} {priority_level}
SLA Target: {sla}
Routing Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

--- ORIGINAL MESSAGE ---
{original_email.get('body', 'No content')[:500]}...

--- ROUTING METADATA ---
System: ORD Shipment Routing Agent
Confidence: Auto-generated
Next Action: Team review and processing
"""
    
    st.markdown("""
    <div class="email-preview">
    """, unsafe_allow_html=True)
    
    st.code(f"""From: {rules['team_mailbox']}
To: {', '.join(contacts)}
Subject: {forwarded_subject}
Priority: {priority_level}
X-Routing-Queue: {queue_name}
X-SLA-Target: {sla}

{forwarded_body}""", language="text")
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Action buttons simulation
    st.markdown("#### ⚡ **Next Actions**")
    col_action1, col_action2, col_action3 = st.columns(3)
    
    with col_action1:
        if st.button(f"✅ Accept by {team[:15]}...", key=f"accept_{queue_name}"):
            st.success(f"✅ Email accepted by {team}")
    
    with col_action2:
        if st.button(f"🔄 Reassign", key=f"reassign_{queue_name}"):
            st.warning("🔄 Reassignment options would appear here")
    
    with col_action3:
        if st.button(f"🚨 Escalate", key=f"escalate_{queue_name}"):
            st.error(f"🚨 Escalating to: {escalation}")
    
    # Show expected timeline
    st.markdown("#### ⏰ **Expected Timeline**")
    timeline_info = f"""
    **Now:** Email received and routed to {team}
    **+15 min:** Team notification sent
    **+{sla}:** SLA target for initial response
    **+{int(sla.replace('h', '').replace('min', '').replace(' hours', '').replace(' hour', '').replace(' minutes', '').replace(' minute', '')) * 2 if 'h' in sla else int(sla.replace('min', '').replace(' minutes', '').replace(' minute', '')) * 2}{'h' if 'h' in sla else 'min'}:** Escalation if no response
    """
    st.info(timeline_info)

def create_eml_file(sample_name: str, sample_content: str) -> bytes:
    """Create a proper .eml file from sample content"""
    try:
        # Parse the sample content to extract components
        lines = sample_content.split('\n')
        from_addr = ""
        to_addr = ""
        subject = ""
        body_lines = []
        in_body = False
        
        for line in lines:
            if line.startswith('From:'):
                from_addr = line.replace('From:', '').strip()
            elif line.startswith('To:'):
                to_addr = line.replace('To:', '').strip()
            elif line.startswith('Subject:'):
                subject = line.replace('Subject:', '').strip()
            elif line.strip() == "" and not in_body:
                in_body = True
            elif in_body:
                body_lines.append(line)
        
        # Create email message
        msg = MimeMultipart()
        msg['From'] = from_addr
        msg['To'] = to_addr
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = f"<{datetime.now().strftime('%Y%m%d%H%M%S')}@ordrouting.local>"
        
        # Add body
        body = '\n'.join(body_lines)
        msg.attach(MimeText(body, 'plain'))
        
        # Return as bytes
        return msg.as_bytes()
        
    except Exception as e:
        st.error(f"Error creating .eml file: {str(e)}")
        return b""

def get_sample_data():
    """Return sample email data for testing"""
    return {
        "Evergreen Pre-Alert": """From: operations@mail.evergreen-line.com
To: noreply-ordchbdocdesk@ups.com
Subject: Shipment Pre-Alert - Container EVGU123456789

Dear UPS Team,

This is a pre-alert notification for incoming container shipment.

Container Number: EVGU123456789
Vessel: Ever Golden
ETA Chicago: March 15, 2024
Shipper: ABC Manufacturing Co.
Consignee: XYZ Distribution LLC

Please prepare for customs clearance and inland transportation.

Best regards,
Evergreen Operations Team""",

        "Account Setup Request": """From: customer.service@newclient.com
To: noreply-ordchbdocdesk@ups.com
Subject: Account Setup Required - Power of Attorney

Hello UPS Team,

We need to set up a new account for our Chicago operations. 
Attached is our completed Power of Attorney form.

Please process our Account Setup request at your earliest convenience.

Company: New Client Corp
Contact: John Smith
Phone: 555-0123

Thank you,
Customer Service Team""",

        "Arrival Notice": """From: port.operations@chicagoport.com
To: noreply-ordchbdocdesk@ups.com
Subject: Container Arrival Notice - Port of Chicago

ARRIVAL NOTICE

Container: MSKU7654321
Vessel: Ocean Star
Arrived: March 10, 2024 08:30 AM
Berth: 5

Shipper: Global Exports Ltd
Consignee: Midwest Imports Inc
Commodity: Electronics

Container available for pickup.

Port Operations""",

        "General Shipment": """From: logistics@supplier.com
To: noreply-ordchbdocdesk@ups.com
Subject: Inland Transportation Request

Dear UPS,

Please arrange inland transportation for our shipment:

Reference: SHP001234
Origin: Chicago Port
Destination: Milwaukee, WI
Cargo: Machinery parts
Weight: 15,000 lbs

Please confirm pickup schedule.

Best regards,
Logistics Team"""
    }

def main():
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>🚢 ORD Shipment Routing Agent</h1>
        <p>Intelligent Document Routing for Chicago ORD Operations</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # API Key input - check secrets first
        default_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        api_key = st.text_input(
            "Claude API Key (Optional)",
            value=default_key,
            type="password",
            help="Enter your Anthropic Claude API key for AI analysis"
        )
        
        if not api_key:
            st.info("💡 Rule-based routing works without API key!")
        
        # Sample data selector
        st.subheader("📝 Sample Data")
        sample_data = get_sample_data()
        selected_sample = st.selectbox(
            "Choose sample email:",
            ["None"] + list(sample_data.keys())
        )
        
        col_load, col_download = st.columns(2)
        
        with col_load:
            if selected_sample != "None":
                if st.button("📥 Load Text", help="Load sample as text in the main area"):
                    st.session_state.sample_content = sample_data[selected_sample]
        
        with col_download:
            if selected_sample != "None":
                eml_content = create_eml_file(selected_sample, sample_data[selected_sample])
                if eml_content:
                    st.download_button(
                        label="📧 Download .eml",
                        data=eml_content,
                        file_name=f"{selected_sample.replace(' ', '_').lower()}.eml",
                        mime="message/rfc822",
                        help="Download as .eml email file"
                    )
        
        # Bulk download option
        if st.button("📦 Download All Sample .eml Files"):
            # Create a zip file with all samples
            import zipfile
            import io
            
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for name, content in sample_data.items():
                    eml_content = create_eml_file(name, content)
                    if eml_content:
                        filename = f"{name.replace(' ', '_').lower()}.eml"
                        zip_file.writestr(filename, eml_content)
            
            st.download_button(
                label="📦 Download ZIP with all samples",
                data=zip_buffer.getvalue(),
                file_name="ord_sample_emails.zip",
                mime="application/zip"
            )
        
        # Display routing rules
        st.subheader("📋 Routing Rules")
        with st.expander("View Routing Logic"):
            st.markdown("""
            **Queue Priority Order:**
            1. 🔴 **Account_Inquiry_US** - POA, Account Setup
            2. 🟠 **ORD_SI-Non_UPS_Shipments** - Evergreen Line
            3. 🟡 **ORD_Pre-Alert_SI** - Pre-Alert notifications
            4. 🟢 **ORD_Ocean_Arrival_Notices** - Arrival notices
            5. ⚪ **Shipment_Initiation_Brkg_Inland_SI** - Default
            """)
    
    # Initialize agent
    try:
        agent = ShipmentRoutingAgent(api_key)
    except Exception as e:
        st.error(f"Failed to initialize agent: {str(e)}")
        st.stop()
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📤 Document Upload & Analysis")
        
        # File uploader
        uploaded_file = st.file_uploader(
            "Choose a file",
            type=['docx', 'pdf', 'txt', 'eml', 'msg', 'jpg', 'jpeg', 'png'],
            help="Upload Word docs, PDFs, emails (.eml/.msg), text files, or images"
        )
        
        # Text input with sample data
        default_content = st.session_state.get('sample_content', '')
        text_input = st.text_area(
            "Or paste email/document content directly:",
            value=default_content,
            height=200,
            placeholder="Paste email headers and content here, or use sample data from sidebar..."
        )
        
        if uploaded_file is not None or text_input.strip():
            # Process the content
            if uploaded_file is not None:
                file_type = uploaded_file.name.split('.')[-1].lower()
                filename = uploaded_file.name
                
                with st.spinner("📄 Extracting text from file..."):
                    content = agent.extract_text_from_file(uploaded_file, file_type)
            else:
                content = text_input
                filename = "pasted_content.txt"
            
            if content.strip() and content != "Image file uploaded - please extract text manually":
                # Display extracted content
                with st.expander("📄 Content Preview"):
                    st.text_area("Extracted Content:", content[:1000] + "..." if len(content) > 1000 else content, height=150, disabled=True)
                
                # Analyze and route
                st.subheader("🎯 Routing Analysis")
                
                col_btn1, col_btn2 = st.columns(2)
                
                with col_btn1:
                    if st.button("⚡ Quick Rule-Based Routing", type="primary"):
                        with st.spinner("🔍 Analyzing content..."):
                            queue, description, confidence, reasons = agent.determine_routing(content, filename)
                            
                            st.success("✅ **Routing Decision Complete**")
                            display_routing_result(queue, description, confidence, reasons, agent.routing_rules)
                            
                            # Show forwarding simulation
                            email_data = agent.parse_email_content(content)
                            simulate_email_forwarding(queue, email_data, agent.routing_rules)
                
                with col_btn2:
                    if st.button("🤖 AI-Powered Analysis") and api_key:
                        with st.spinner("🤖 Running Claude analysis..."):
                            claude_result = agent.analyze_with_claude(content, filename)
                            
                            st.success("✅ **AI Analysis Complete**")
                            
                            # Display Claude results
                            col_ai1, col_ai2, col_ai3 = st.columns(3)
                            with col_ai1:
                                st.metric("Document Type", claude_result.get('document_type', 'Unknown'))
                            with col_ai2:
                                st.metric("Urgency Level", f"{claude_result.get('urgency_level', 3)}/5")
                            with col_ai3:
                                st.metric("AI Confidence", f"{claude_result.get('confidence_score', 0):.1%}")
                            
                            # Display recommended queue
                            recommended_queue = claude_result.get('recommended_queue', 'Unknown')
                            ai_reasons = claude_result.get('reasons', [])
                            display_routing_result(
                                recommended_queue, 
                                "AI-powered routing decision", 
                                claude_result.get('confidence_score', 0),
                                ai_reasons,
                                agent.routing_rules
                            )
                            
                            # Show AI forwarding simulation
                            email_data = agent.parse_email_content(content)
                            simulate_email_forwarding(recommended_queue, email_data, agent.routing_rules)
                            
                            # Display entities if found
                            entities = claude_result.get('key_entities', [])
                            if entities:
                                st.markdown("**🏢 Key Entities Found:**")
                                for entity in entities:
                                    st.write(f"• {entity}")
                    
                    elif st.button("🤖 AI-Powered Analysis") and not api_key:
                        st.warning("🔑 Please enter Claude API key in the sidebar for AI analysis")
    
    with col2:
        st.subheader("📧 Team Contacts")
        
        # Display contact info for each team
        with st.expander("📋 Routing Team Directory"):
            for queue_name, queue_info in agent.routing_rules["routing_queues"].items():
                team_name = queue_info.get('team', 'Unknown Team')
                contacts = queue_info.get('contacts', [])
                sla = queue_info.get('sla', 'N/A')
                
                st.markdown(f"**{team_name}**")
                for contact in contacts:
                    st.write(f"• {contact}")
                st.write(f"⏱️ SLA: {sla}")
                st.write("---")
        
        # Main contacts
        st.info(f"""
        **📥 Main Inbox:**  
        `{agent.routing_rules['team_mailbox']}`
        
        **📨 Distribution:**  
        `{agent.routing_rules['distribution_list']}`
        """)
        
        # Emergency contacts
        st.error("""
        **🚨 Emergency Escalation:**
        - Operations Manager: ops.manager@ups.com
        - 24/7 Hotline: 1-800-UPS-HELP
        - Critical Issues: critical.ops@ups.com
        """)
        
        # Help section
        st.subheader("❓ How to Use")
        with st.expander("Quick Guide"):
            st.markdown("""
            **📧 Email Files (.eml/.msg):**
            - Upload .eml or .msg files directly
            - Download sample .eml files to test
            - System extracts headers and body automatically
            
            **📄 Documents:**
            1. **Upload** a document or **paste** email content
            2. Click **Quick Routing** for rule-based analysis
            3. Click **AI Analysis** (with API key) for advanced routing
            4. Review routing decision and confidence score
            5. Check reasons for routing logic
            
            **📁 Supported Formats:**
            - .eml (Email files)
            - .msg (Outlook emails)
            - .docx (Word documents)
            - .pdf (PDF files)
            - .txt (Text files)
            - Images (manual text extraction)
            """)
        
        # File format info
        with st.expander("📧 Email Format Support"):
            st.markdown("""
            **✅ .eml files:** Standard email format
            - Proper header parsing
            - Multi-part message support
            - Attachment detection
            
            **✅ .msg files:** Microsoft Outlook format
            - Full message extraction
            - Metadata preservation
            - Rich formatting support
            
            **💡 Tip:** Download sample .eml files above to test!
            """)

    # Footer with routing reference
    st.markdown("---")
    
    # Routing reference table
    st.subheader("📋 **Complete Routing Reference**")
    
    routing_ref_data = []
    for queue_name, queue_info in agent.routing_rules["routing_queues"].items():
        routing_ref_data.append({
            "Queue": queue_name.replace("ORD_", "").replace("_", " "),
            "Team": queue_info.get('team', 'Unknown'),
            "Triggers": ", ".join(queue_info.get('keywords', queue_info.get('subject_keywords', queue_info.get('content_keywords', ['Domain check' if 'from_domain' in queue_info else 'Default'])))),
            "SLA": queue_info.get('sla', 'N/A'),
            "Primary Contact": queue_info.get('contacts', ['N/A'])[0] if queue_info.get('contacts') else 'N/A'
        })
    
    routing_df = pd.DataFrame(routing_ref_data)
    st.dataframe(routing_df, hide_index=True, use_container_width=True)
    
    # Show sample forwarding for reference
    with st.expander("📧 **Sample Email Forwarding Examples**"):
        st.markdown("""
        **Example 1: Account Setup Email**
        ```
        From: customer@company.com → account.setup@ups.com
        Subject: [Account_Inquiry_US] Account Setup Required - Power of Attorney
        Team: Customer Account Services Team
        SLA: 4 hours
        ```
        
        **Example 2: Pre-Alert Notification**  
        ```
        From: shipper@company.com → prealert.team@ups.com
        Subject: [ORD_Pre-Alert_SI] Shipment Pre-Alert - Container ABC123
        Team: Shipment Coordination Team
        SLA: 1 hour
        ```
        
        **Example 3: Arrival Notice**
        ```
        From: port@chicago.com → port.operations@ups.com
        Subject: [ORD_Ocean_Arrival_Notices] Container Arrival Notice
        Team: Port Operations Team  
        SLA: 30 minutes
        ```
        """)
    
    st.markdown(
        "<div style='text-align: center; color: #666;'>"
        "🚢 UPS ORD Shipment Routing Agent | Powered by Claude AI & Streamlit<br>"
        "📧 All emails routed to appropriate teams with SLA tracking and escalation protocols"
        "</div>",
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
