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
    page_title="Agentic ORD Routing System",
    page_icon="🤖",
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
    .agentic-analysis {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

class ShipmentRoutingAgent:
    def __init__(self, api_key: str):
        """Initialize the agentic routing agent with Claude API"""
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else None
        self.routing_rules = self._load_routing_rules()
        self.confidence_threshold = 0.8  # Threshold for autonomous routing
        self.learning_history = []  # Track routing decisions for learning
        
    def _load_routing_rules(self) -> Dict:
        """Load the routing rules based on the ORD shipment initiation document"""
        return {
            "team_mailbox": "noreply-ordchbdocdesk@ups.com",
            "distribution_list": "ordchbdocdesk@ups.com",
            
            "routing_queues": {
                "Account_Inquiry_US": {
                    "description": "POA, Account Setup, Account Needed requests",
                    "keywords": ["Power of Attorney", "POA", "Account Needed", "Account Setup", "Legal Authorization", "Company Registration"],
                    "priority": 1,
                    "color": "#dc3545",
                    "team": "Customer Account Services Team",
                    "contacts": [
                        "account.setup@ups.com",
                        "customer.onboarding@ups.com",
                        "legal.compliance@ups.com"
                    ],
                    "sla": "4 hours",
                    "escalation": "account.manager@ups.com",
                    "autonomous_actions": ["auto_acknowledge", "priority_flag", "legal_review_trigger"],
                    "business_impact": "high"
                },
                "ORD_SI-Non_UPS_Shipments": {
                    "description": "Emails from Evergreen Line and other external carriers",
                    "from_domains": ["@mail.evergreen-line.com", "@evergreen.com", "@evergreen-line.com"],
                    "priority": 2,
                    "color": "#fd7e14",
                    "team": "External Carrier Relations Team",
                    "contacts": [
                        "carrier.relations@ups.com",
                        "evergreen.coordinator@ups.com"
                    ],
                    "sla": "2 hours",
                    "escalation": "carrier.manager@ups.com",
                    "autonomous_actions": ["auto_acknowledge", "carrier_sync", "tracking_update"],
                    "business_impact": "high"
                },
                "ORD_Pre-Alert_SI": {
                    "description": "Pre-Alert notifications for incoming shipments",
                    "subject_keywords": ["Pre-Alert", "Pre Alert", "PreAlert", "Advance Notice", "Incoming Shipment"],
                    "content_patterns": ["ETA", "Expected Arrival", "Advance Notification", "Container.*arriving"],
                    "priority": 3,
                    "color": "#ffc107",
                    "team": "Shipment Coordination Team",
                    "contacts": [
                        "prealert.team@ups.com",
                        "shipment.coordination@ups.com"
                    ],
                    "sla": "1 hour",
                    "escalation": "operations.supervisor@ups.com",
                    "autonomous_actions": ["auto_acknowledge", "schedule_coordination", "resource_allocation"],
                    "business_impact": "critical"
                },
                "ORD_Ocean_Arrival_Notices": {
                    "description": "Ocean arrival notices and port notifications",
                    "content_keywords": ["Arrival Notice", "Port Arrival", "Vessel Arrived", "Container Available", "Discharge Complete"],
                    "priority": 4,
                    "color": "#28a745",
                    "team": "Port Operations Team",
                    "contacts": [
                        "port.operations@ups.com",
                        "arrival.notices@ups.com",
                        "customs.clearance@ups.com"
                    ],
                    "sla": "30 minutes",
                    "escalation": "port.supervisor@ups.com",
                    "autonomous_actions": ["auto_acknowledge", "customs_notification", "pickup_scheduling"],
                    "business_impact": "critical"
                },
                "Shipment_Initiation_Brkg_Inland_SI": {
                    "description": "Default queue for general shipment initiations and brokerage",
                    "priority": 5,
                    "color": "#6c757d",
                    "team": "General Shipment Processing Team",
                    "contacts": [
                        "shipment.processing@ups.com",
                        "inland.transport@ups.com"
                    ],
                    "sla": "6 hours",
                    "escalation": "processing.manager@ups.com",
                    "autonomous_actions": ["auto_acknowledge", "route_optimization", "capacity_check"],
                    "business_impact": "medium"
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
    
    def intelligent_content_analysis(self, content: str, filename: str = "") -> Dict:
        """Advanced agentic analysis of content using multiple intelligence layers"""
        
        # Layer 1: Pattern Recognition
        email_data = self.parse_email_content(content)
        patterns = self._detect_patterns(content, email_data)
        
        # Layer 2: Business Context Understanding
        business_context = self._analyze_business_context(content, email_data)
        
        # Layer 3: Urgency and Priority Assessment
        urgency_analysis = self._assess_urgency(content, email_data, patterns)
        
        # Layer 4: Routing Decision with Confidence
        routing_decision = self._make_routing_decision(patterns, business_context, urgency_analysis)
        
        # Layer 5: Autonomous Actions Planning
        autonomous_actions = self._plan_autonomous_actions(routing_decision, urgency_analysis)
        
        return {
            "patterns": patterns,
            "business_context": business_context,
            "urgency_analysis": urgency_analysis,
            "routing_decision": routing_decision,
            "autonomous_actions": autonomous_actions,
            "confidence": routing_decision.get("confidence", 0.5),
            "reasoning_chain": self._build_reasoning_chain(patterns, business_context, urgency_analysis, routing_decision)
        }
    
    def _detect_patterns(self, content: str, email_data: Dict) -> Dict:
        """Detect patterns in email content using intelligent analysis"""
        patterns = {
            "email_type": "unknown",
            "sender_type": "unknown",
            "content_indicators": [],
            "structural_elements": [],
            "business_signals": []
        }
        
        content_lower = content.lower()
        subject = email_data.get("subject", "").lower()
        sender = email_data.get("from", "").lower()
        
        # Detect email type patterns
        if any(word in content_lower for word in ["power of attorney", "poa", "account setup", "legal authorization"]):
            patterns["email_type"] = "legal_documentation"
            patterns["content_indicators"].append("legal_documents")
            
        elif any(domain in sender for domain in ["evergreen", "carrier", "shipping"]):
            patterns["email_type"] = "carrier_communication"
            patterns["sender_type"] = "external_carrier"
            
        elif any(word in subject for word in ["pre-alert", "prealert", "advance notice"]):
            patterns["email_type"] = "operational_notification"
            patterns["content_indicators"].append("pre_alert_notification")
            
        elif any(word in content_lower for word in ["arrival notice", "port arrival", "vessel arrived"]):
            patterns["email_type"] = "arrival_notification"
            patterns["content_indicators"].append("arrival_notice")
            
        # Detect structural elements
        if re.search(r'container.*[A-Z]{4}\d{7}', content_lower):
            patterns["structural_elements"].append("container_number")
            
        if re.search(r'eta|expected.*arrival|arriving.*\d{1,2}[/-]\d{1,2}', content_lower):
            patterns["structural_elements"].append("arrival_date")
            
        if re.search(r'vessel.*\w+|ship.*\w+', content_lower):
            patterns["structural_elements"].append("vessel_info")
            
        # Detect business signals
        if any(word in content_lower for word in ["urgent", "asap", "immediate", "critical"]):
            patterns["business_signals"].append("high_urgency")
            
        if any(word in content_lower for word in ["customs", "clearance", "duties", "taxes"]):
            patterns["business_signals"].append("customs_required")
            
        return patterns
    
    def _analyze_business_context(self, content: str, email_data: Dict) -> Dict:
        """Analyze business context and implications"""
        context = {
            "business_unit": "unknown",
            "geographic_scope": "unknown",
            "service_type": "unknown",
            "customer_tier": "unknown",
            "compliance_requirements": [],
            "operational_impact": "medium"
        }
        
        content_lower = content.lower()
        
        # Determine business unit
        if "chicago" in content_lower or "ord" in content_lower:
            context["geographic_scope"] = "chicago_ord"
            
        # Determine service type
        if any(word in content_lower for word in ["ocean", "sea", "vessel", "port"]):
            context["service_type"] = "ocean_freight"
        elif any(word in content_lower for word in ["inland", "truck", "rail", "domestic"]):
            context["service_type"] = "inland_transport"
            
        # Assess compliance requirements
        if any(word in content_lower for word in ["poa", "power of attorney", "legal"]):
            context["compliance_requirements"].append("legal_documentation")
        if any(word in content_lower for word in ["customs", "duties", "import", "export"]):
            context["compliance_requirements"].append("customs_compliance")
            
        return context
    
    def _assess_urgency(self, content: str, email_data: Dict, patterns: Dict) -> Dict:
        """Intelligent urgency assessment"""
        urgency = {
            "level": 3,  # 1-5 scale
            "factors": [],
            "time_sensitivity": "normal",
            "business_impact": "medium",
            "escalation_needed": False
        }
        
        content_lower = content.lower()
        
        # Time-sensitive indicators
        if any(word in content_lower for word in ["today", "asap", "urgent", "immediate"]):
            urgency["level"] = min(5, urgency["level"] + 2)
            urgency["factors"].append("explicit_urgency_keywords")
            urgency["time_sensitivity"] = "high"
            
        # Business impact indicators
        if patterns.get("email_type") == "arrival_notification":
            urgency["level"] = min(5, urgency["level"] + 1)
            urgency["factors"].append("arrival_notification_time_critical")
            urgency["business_impact"] = "high"
            
        if patterns.get("email_type") == "legal_documentation":
            urgency["level"] = min(5, urgency["level"] + 1)
            urgency["factors"].append("legal_documentation_compliance")
            
        # Pattern-based urgency
        if "high_urgency" in patterns.get("business_signals", []):
            urgency["level"] = min(5, urgency["level"] + 1)
            urgency["escalation_needed"] = urgency["level"] >= 4
            
        return urgency
    
    def _make_routing_decision(self, patterns: Dict, business_context: Dict, urgency_analysis: Dict) -> Dict:
        """Intelligent routing decision using agentic reasoning"""
        
        decision = {
            "queue": "Shipment_Initiation_Brkg_Inland_SI",  # Default
            "confidence": 0.5,
            "reasons": [],
            "alternative_queues": [],
            "escalation_recommended": False
        }
        
        # Rule-based routing with intelligence
        content_indicators = patterns.get("content_indicators", [])
        email_type = patterns.get("email_type", "unknown")
        
        # Account Inquiry routing
        if email_type == "legal_documentation" or "legal_documents" in content_indicators:
            decision["queue"] = "Account_Inquiry_US"
            decision["confidence"] = 0.9
            decision["reasons"].append("Legal documentation detected (POA/Account Setup)")
            
        # External carrier routing
        elif patterns.get("sender_type") == "external_carrier":
            decision["queue"] = "ORD_SI-Non_UPS_Shipments"
            decision["confidence"] = 0.95
            decision["reasons"].append("External carrier communication identified")
            
        # Pre-alert routing
        elif "pre_alert_notification" in content_indicators:
            decision["queue"] = "ORD_Pre-Alert_SI"
            decision["confidence"] = 0.9
            decision["reasons"].append("Pre-alert notification pattern matched")
            
        # Arrival notice routing
        elif "arrival_notice" in content_indicators:
            decision["queue"] = "ORD_Ocean_Arrival_Notices"
            decision["confidence"] = 0.85
            decision["reasons"].append("Arrival notice pattern detected")
            
        # Adjust confidence based on urgency and context
        if urgency_analysis["level"] >= 4:
            decision["confidence"] = min(1.0, decision["confidence"] + 0.1)
            decision["escalation_recommended"] = True
            decision["reasons"].append("High urgency detected - confidence boosted")
            
        return decision
    
    def _plan_autonomous_actions(self, routing_decision: Dict, urgency_analysis: Dict) -> List[Dict]:
        """Plan autonomous actions based on routing decision"""
        
        actions = []
        queue_name = routing_decision["queue"]
        queue_info = self.routing_rules["routing_queues"].get(queue_name, {})
        autonomous_capabilities = queue_info.get("autonomous_actions", [])
        
        # Standard acknowledgment for all routes
        actions.append({
            "action": "auto_acknowledge",
            "description": "Send automatic acknowledgment to sender",
            "timing": "immediate",
            "confidence": 0.95
        })
        
        # Queue-specific autonomous actions
        if "priority_flag" in autonomous_capabilities and urgency_analysis["level"] >= 4:
            actions.append({
                "action": "priority_flag",
                "description": "Flag as high priority in team queue",
                "timing": "immediate",
                "confidence": 0.9
            })
            
        if "carrier_sync" in autonomous_capabilities:
            actions.append({
                "action": "carrier_sync",
                "description": "Sync information with carrier systems",
                "timing": "within_15_minutes",
                "confidence": 0.8
            })
            
        if "customs_notification" in autonomous_capabilities:
            actions.append({
                "action": "customs_notification",
                "description": "Notify customs team of arrival",
                "timing": "immediate",
                "confidence": 0.85
            })
            
        # Escalation actions
        if routing_decision.get("escalation_recommended"):
            actions.append({
                "action": "escalation_alert",
                "description": f"Send escalation alert to {queue_info.get('escalation', 'supervisor')}",
                "timing": "immediate",
                "confidence": 0.9
            })
            
        return actions
    
    def _build_reasoning_chain(self, patterns: Dict, business_context: Dict, urgency_analysis: Dict, routing_decision: Dict) -> List[str]:
        """Build transparent reasoning chain for decision explanation"""
        
        chain = []
        
        # Pattern analysis reasoning
        if patterns.get("email_type") != "unknown":
            chain.append(f"🔍 Identified email type: {patterns['email_type']}")
            
        if patterns.get("sender_type") != "unknown":
            chain.append(f"👤 Sender classification: {patterns['sender_type']}")
            
        # Business context reasoning
        if business_context.get("service_type") != "unknown":
            chain.append(f"🚢 Service type detected: {business_context['service_type']}")
            
        if business_context.get("compliance_requirements"):
            chain.append(f"⚖️ Compliance requirements: {', '.join(business_context['compliance_requirements'])}")
            
        # Urgency reasoning
        chain.append(f"⏰ Urgency level: {urgency_analysis['level']}/5 ({urgency_analysis['time_sensitivity']})")
        
        if urgency_analysis.get("factors"):
            chain.append(f"📈 Urgency factors: {', '.join(urgency_analysis['factors'])}")
            
        # Final decision reasoning
        chain.append(f"🎯 Final routing: {routing_decision['queue']} (confidence: {routing_decision['confidence']:.1%})")
        
        return chain
    
    def determine_routing(self, content: str, filename: str = "") -> Tuple[str, str, float, List[str]]:
        """Determine routing using agentic intelligence"""
        
        # Use the new agentic analysis system
        analysis = self.intelligent_content_analysis(content, filename)
        
        routing_decision = analysis["routing_decision"]
        reasoning_chain = analysis["reasoning_chain"]
        
        return (
            routing_decision["queue"],
            self.routing_rules["routing_queues"][routing_decision["queue"]]["description"],
            routing_decision["confidence"],
            reasoning_chain
        )
    
    def get_agentic_analysis(self, content: str, filename: str = "") -> Dict:
        """Get full agentic analysis for display"""
        return self.intelligent_content_analysis(content, filename)
    
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

def display_agentic_analysis(analysis: Dict):
    """Display comprehensive agentic analysis results"""
    
    st.markdown("""
    <div class="agentic-analysis">
        <h3 style="margin-top: 0;">🤖 Agentic Intelligence Analysis</h3>
    </div>
    """, unsafe_allow_html=True)
    
    # Analysis Overview
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        email_type = analysis["patterns"].get("email_type", "unknown").replace("_", " ").title()
        st.metric("Email Type", email_type)
    
    with col2:
        urgency_level = analysis["urgency_analysis"]["level"]
        urgency_color = "🔴" if urgency_level >= 4 else "🟠" if urgency_level >= 3 else "🟢"
        st.metric("Urgency Level", f"{urgency_color} {urgency_level}/5")
    
    with col3:
        confidence = analysis["confidence"]
        confidence_color = "🟢" if confidence >= 0.8 else "🟡" if confidence >= 0.6 else "🔴"
        st.metric("Confidence", f"{confidence_color} {confidence:.1%}")
    
    with col4:
        business_impact = analysis["urgency_analysis"]["business_impact"]
        impact_color = "🔴" if business_impact == "critical" else "🟠" if business_impact == "high" else "🟢"
        st.metric("Business Impact", f"{impact_color} {business_impact.title()}")
    
    # Reasoning Chain
    st.markdown("#### 🧠 **Intelligent Reasoning Chain**")
    reasoning_chain = analysis["reasoning_chain"]
    
    for i, step in enumerate(reasoning_chain, 1):
        st.markdown(f"**Step {i}:** {step}")
    
    # Pattern Detection Results
    with st.expander("🔍 **Pattern Detection Analysis**"):
        patterns = analysis["patterns"]
        
        col_pat1, col_pat2 = st.columns(2)
        
        with col_pat1:
            st.markdown("**Content Indicators:**")
            indicators = patterns.get("content_indicators", [])
            if indicators:
                for indicator in indicators:
                    st.write(f"✅ {indicator.replace('_', ' ').title()}")
            else:
                st.write("No specific indicators detected")
                
            st.markdown("**Structural Elements:**")
            elements = patterns.get("structural_elements", [])
            if elements:
                for element in elements:
                    st.write(f"📋 {element.replace('_', ' ').title()}")
            else:
                st.write("No structural elements found")
        
        with col_pat2:
            st.markdown("**Business Signals:**")
            signals = patterns.get("business_signals", [])
            if signals:
                for signal in signals:
                    st.write(f"📊 {signal.replace('_', ' ').title()}")
            else:
                st.write("No business signals detected")
                
            st.markdown("**Sender Classification:**")
            sender_type = patterns.get("sender_type", "unknown")
            st.write(f"👤 {sender_type.replace('_', ' ').title()}")
    
    # Business Context Analysis
    with st.expander("🏢 **Business Context Analysis**"):
        context = analysis["business_context"]
        
        col_ctx1, col_ctx2 = st.columns(2)
        
        with col_ctx1:
            st.markdown("**Service Context:**")
            st.write(f"🌎 Geographic Scope: {context.get('geographic_scope', 'Unknown').replace('_', ' ').title()}")
            st.write(f"🚚 Service Type: {context.get('service_type', 'Unknown').replace('_', ' ').title()}")
            st.write(f"💼 Business Unit: {context.get('business_unit', 'Unknown').replace('_', ' ').title()}")
        
        with col_ctx2:
            st.markdown("**Compliance Requirements:**")
            requirements = context.get("compliance_requirements", [])
            if requirements:
                for req in requirements:
                    st.write(f"⚖️ {req.replace('_', ' ').title()}")
            else:
                st.write("No specific compliance requirements")
            
            st.write(f"📈 Operational Impact: {context.get('operational_impact', 'Unknown').title()}")
    
    # Autonomous Actions Planning
    st.markdown("#### 🚀 **Planned Autonomous Actions**")
    actions = analysis["autonomous_actions"]
    
    if actions:
        for action in actions:
            action_name = action["action"].replace("_", " ").title()
            confidence_badge = "🟢" if action["confidence"] >= 0.8 else "🟡" if action["confidence"] >= 0.6 else "🔴"
            
            st.markdown(f"""
            **{action_name}** {confidence_badge} {action["confidence"]:.1%}
            - *{action["description"]}*
            - ⏰ Timing: {action["timing"].replace("_", " ").title()}
            """)
    else:
        st.info("No autonomous actions planned for this routing decision")

def display_routing_result(queue_name: str, description: str, confidence: float, reasons: List[str], rules: Dict, analysis: Dict = None):
    """Display routing result with styled card and agentic insights"""
    queue_info = rules["routing_queues"].get(queue_name, {})
    color = queue_info.get("color", "#6c757d")
    
    confidence_class = "confidence-high" if confidence > 0.8 else "confidence-medium" if confidence > 0.5 else "confidence-low"
    
    # Main routing card
    st.markdown(f"""
    <div class="routing-card {confidence_class}">
        <h4 style="color: {color}; margin: 0;">🎯 AGENTIC ROUTING DECISION</h4>
        <h5 style="color: {color}; margin: 0.5rem 0;">📍 {queue_name}</h5>
        <p style="margin: 0.5rem 0;"><strong>Description:</strong> {description}</p>
        <p style="margin: 0.5rem 0;"><strong>Confidence:</strong> {confidence:.1%}</p>
        <p style="margin: 0;"><strong>Team:</strong> {queue_info.get('team', 'Unknown Team')}</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Show agentic analysis if available
    if analysis:
        display_agentic_analysis(analysis)
    
    # Traditional reasons (if no agentic analysis)
    elif reasons:
        st.markdown("**🔍 Routing Reasons:**")
        for reason in reasons:
            st.write(f"• {reason}")
    
    # Business Impact Assessment
    business_impact = queue_info.get("business_impact", "medium")
    if business_impact in ["high", "critical"]:
        impact_color = "🔴" if business_impact == "critical" else "🟠"
        st.warning(f"{impact_color} **High Business Impact Queue** - {business_impact.upper()} priority processing required")
    
    # Autonomous capabilities
    autonomous_actions = queue_info.get("autonomous_actions", [])
    if autonomous_actions:
        st.info(f"🤖 **Autonomous Capabilities:** {', '.join([action.replace('_', ' ').title() for action in autonomous_actions])}")

def simulate_email_forwarding(queue_name: str, original_email: Dict, rules: Dict, autonomous_actions: List[Dict] = None):
    """Simulate where the email would be forwarded after routing with autonomous actions"""
    queue_info = rules["routing_queues"].get(queue_name, {})
    
    st.markdown("""
    <div class="forwarding-simulation">
        <h3 style="color: #007bff; margin-top: 0;">📧 Agentic Email Forwarding Simulation</h3>
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
        
        # Show autonomous actions if available
        if autonomous_actions:
            st.markdown("#### 🤖 **Autonomous Actions Executed**")
            for action in autonomous_actions:
                action_name = action["action"].replace("_", " ").title()
                confidence_badge = "✅" if action["confidence"] >= 0.8 else "⚠️" if action["confidence"] >= 0.6 else "❌"
                timing_badge = "🟢" if action["timing"] == "immediate" else "🟡"
                
                st.success(f"{confidence_badge} **{action_name}** {timing_badge}")
                st.caption(f"↳ {action['description']}")
    
    with col2:
        st.markdown("#### 📤 **Routed To Team**")
        
        contacts = queue_info.get('contacts', [])
        team = queue_info.get('team', 'Unknown Team')
        sla = queue_info.get('sla', 'N/A')
        escalation = queue_info.get('escalation', 'N/A')
        business_impact = queue_info.get('business_impact', 'medium')
        
        # Primary contacts with business impact
        impact_color = "🔴" if business_impact == "critical" else "🟠" if business_impact == "high" else "🟢"
        
        st.success(f"""
        **Team:** {team}
        **Queue:** {queue_name}
        **SLA Target:** {sla}
        **Impact:** {impact_color} {business_impact.title()}
        """)
        
        st.markdown("**📬 Recipients:**")
        for i, contact in enumerate(contacts):
            priority = "Primary" if i == 0 else "CC"
            st.write(f"• **{priority}:** {contact}")
        
        if escalation != 'N/A':
            st.write(f"• **Escalation:** {escalation}")
    
    # Enhanced action buttons with agentic capabilities
    st.markdown("#### ⚡ **Agentic Actions Available**")
    
    col_action1, col_action2, col_action3, col_action4 = st.columns(4)
    
    with col_action1:
        if st.button(f"✅ Accept & Auto-Process", key=f"accept_{queue_name}"):
            st.success(f"✅ Email accepted by {team} - Autonomous processing initiated")
    
    with col_action2:
        if st.button(f"🤖 Execute Auto-Actions", key=f"auto_{queue_name}"):
            st.info("🤖 Executing configured autonomous actions...")
    
    with col_action3:
        if st.button(f"🔄 Smart Reassign", key=f"reassign_{queue_name}"):
            st.warning("🔄 AI-powered reassignment analysis initiated")
    
    with col_action4:
        if st.button(f"🚨 Intelligent Escalate", key=f"escalate_{queue_name}"):
            st.error(f"🚨 Smart escalation to: {escalation}")

def create_eml_file(sample_name: str, sample_content: str) -> bytes:
    """Create a proper .eml file from sample content"""
    try:
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
        
        msg = MimeMultipart()
        msg['From'] = from_addr
        msg['To'] = to_addr
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = f"<{datetime.now().strftime('%Y%m%d%H%M%S')}@ordrouting.local>"
        
        body = '\n'.join(body_lines)
        msg.attach(MimeText(body, 'plain'))
        
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
        <h1>🤖 Agentic ORD Shipment Routing System</h1>
        <p>AI-Powered Intelligent Document Routing with Autonomous Actions for Chicago ORD Operations</p>
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
            st.info("💡 Agentic routing works without API key!")
        
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
        
        # Display routing rules
        st.subheader("🧠 Agentic Routing Intelligence")
        with st.expander("View Intelligent Routing Logic"):
            st.markdown("""
            **Multi-Layer Analysis:**
            1. 🔍 **Pattern Recognition** - Content & structural analysis
            2. 🏢 **Business Context** - Service type & compliance detection  
            3. ⏰ **Urgency Assessment** - Priority & impact evaluation
            4. 🎯 **Intelligent Routing** - Confidence-based decisions
            5. 🤖 **Autonomous Actions** - Automated processing initiation
            
            **Routing Queues:**
            1. 🔴 **Account_Inquiry_US** - POA, Account Setup (4h SLA)
            2. 🟠 **ORD_SI-Non_UPS_Shipments** - Evergreen Line (2h SLA)
            3. 🟡 **ORD_Pre-Alert_SI** - Pre-Alert notifications (1h SLA)
            4. 🟢 **ORD_Ocean_Arrival_Notices** - Arrival notices (30min SLA)
            5. ⚪ **Shipment_Initiation_Brkg_Inland_SI** - Default (6h SLA)
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
        st.subheader("📤 Document Upload & Agentic Analysis")
        
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
                st.subheader("🎯 Agentic Routing Analysis")
                
                col_btn1, col_btn2, col_btn3 = st.columns(3)
                
                with col_btn1:
                    if st.button("⚡ Quick Agentic Routing", type="primary"):
                        with st.spinner("🤖 Running agentic analysis..."):
                            queue, description, confidence, reasons = agent.determine_routing(content, filename)
                            
                            st.success("✅ **Agentic Routing Complete**")
                            
                            # Get full agentic analysis
                            analysis = agent.get_agentic_analysis(content, filename)
                            display_routing_result(queue, description, confidence, reasons, agent.routing_rules, analysis)
                            
                            # Show forwarding simulation
                            email_data = agent.parse_email_content(content)
                            simulate_email_forwarding(queue, email_data, agent.routing_rules, analysis.get("autonomous_actions"))
                
                with col_btn2:
                    if st.button("🧠 Deep Intelligence Analysis"):
                        with st.spinner("🔍 Performing deep agentic analysis..."):
                            # Get comprehensive agentic analysis
                            analysis = agent.get_agentic_analysis(content, filename)
                            
                            st.success("✅ **Deep Intelligence Analysis Complete**")
                            
                            # Display detailed agentic analysis
                            display_agentic_analysis(analysis)
                            
                            # Show routing decision
                            routing_decision = analysis["routing_decision"]
                            queue_name = routing_decision["queue"]
                            queue_info = agent.routing_rules["routing_queues"][queue_name]
                            
                            st.markdown("#### 🎯 **Final Routing Decision**")
                            display_routing_result(
                                queue_name,
                                queue_info["description"],
                                routing_decision["confidence"],
                                routing_decision["reasons"],
                                agent.routing_rules
                            )
                            
                            # Show autonomous actions that would be executed
                            autonomous_actions = analysis["autonomous_actions"]
                            if autonomous_actions:
                                st.markdown("#### 🚀 **Autonomous Actions Execution**")
                                for action in autonomous_actions:
                                    action_status = "✅ READY" if action["confidence"] >= 0.8 else "⚠️ REVIEW" if action["confidence"] >= 0.6 else "❌ MANUAL"
                                    st.info(f"**{action['action'].replace('_', ' ').title()}** - {action_status}")
                            
                            # Show forwarding simulation
                            email_data = agent.parse_email_content(content)
                            simulate_email_forwarding(queue_name, email_data, agent.routing_rules, autonomous_actions)
                
                with col_btn3:
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
                business_impact = queue_info.get('business_impact', 'medium')
                autonomous_actions = queue_info.get('autonomous_actions', [])
                
                st.markdown(f"**{team_name}**")
                for contact in contacts:
                    st.write(f"• {contact}")
                st.write(f"⏱️ SLA: {sla}")
                st.write(f"📊 Impact: {business_impact.title()}")
                st.write(f"🤖 Auto Actions: {len(autonomous_actions)}")
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
        with st.expander("Agentic Intelligence Guide"):
            st.markdown("""
            **🤖 Agentic Intelligence:**
            - Multi-layer pattern recognition and analysis
            - Business context understanding and compliance detection
            - Autonomous action planning and execution
            - Confidence-based routing with transparent reasoning
            
            **📧 Email Files (.eml/.msg):**
            - Upload .eml or .msg files directly
            - Download sample .eml files to test
            - System extracts headers and body automatically
            
            **📄 Documents:**
            1. **Upload** a document or **paste** email content
            2. Click **Quick Agentic Routing** for intelligent analysis
            3. Click **Deep Intelligence Analysis** for comprehensive insights
            4. Click **AI Analysis** (with API key) for Claude integration
            5. Review routing decision, confidence, and autonomous actions
            
            **📁 Supported Formats:**
            - .eml (Email files)
            - .msg (Outlook emails)
            - .docx (Word documents)
            - .pdf (PDF files)
            - .txt (Text files)
            - Images (manual text extraction)
            """)

    # Footer with routing reference
    st.markdown("---")
    
    # Routing reference table
    st.subheader("📋 **Complete Agentic Routing Reference**")
    
    routing_ref_data = []
    for queue_name, queue_info in agent.routing_rules["routing_queues"].items():
        routing_ref_data.append({
            "Queue": queue_name.replace("ORD_", "").replace("_", " "),
            "Team": queue_info.get('team', 'Unknown'),
            "SLA": queue_info.get('sla', 'N/A'),
            "Business Impact": queue_info.get('business_impact', 'medium').title(),
            "Auto Actions": len(queue_info.get('autonomous_actions', [])),
            "Primary Contact": queue_info.get('contacts', ['N/A'])[0] if queue_info.get('contacts') else 'N/A'
        })
    
    routing_df = pd.DataFrame(routing_ref_data)
    st.dataframe(routing_df, hide_index=True, use_container_width=True)
    
    st.markdown(
        "<div style='text-align: center; color: #666;'>"
        "🤖 UPS ORD Agentic Routing System | Powered by Multi-Layer AI Intelligence & Autonomous Actions<br>"
        "📧 Intelligent email routing with pattern recognition, business context analysis, and autonomous processing"
        "</div>",
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
