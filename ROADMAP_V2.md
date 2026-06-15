# DIMO v2: The Omnipresent Assistant Roadmap

Building upon the robust, hybrid LangGraph architecture established in v1, **DIMO v2** aims to transition from a reactive tool to a proactive, omnipresent personal assistant. The next major version focuses on true autonomy, deeper environmental integrations, and continuous multimodal interactions.

---

## 🚀 1. Autonomous Agents
Transitioning DIMO from a strictly user-prompted loop to a continuous, self-directed background daemon.
- **Background Daemon Mode:** DIMO runs continuously as a background process, able to monitor system state and trigger workflows without explicit user prompts.
- **Multi-Agent Orchestration:** Specialized sub-agents (e.g., a "Research Agent," a "Coding Agent," an "Email Triage Agent") that communicate and delegate tasks among themselves to solve complex, multi-day goals.
- **Proactive Interventions:** The ability for DIMO to notice patterns (e.g., "You are struggling with this code") and proactively offer solutions or context.

## 🧠 2. Personal Memory Improvements
Evolving the Qdrant/JSON episodic memory into a rich, interconnected knowledge graph.
- **Semantic Knowledge Graphs:** Moving beyond flat fact storage to map relationships (e.g., "John is the manager of [User], John prefers concise emails").
- **Implicit Context Gathering:** Automatically updating user preferences, routines, and ongoing project context strictly by observing background workflows.
- **Temporal Memory:** Enhanced capability to remember *when* things happened and track the evolution of facts over time.

## 📅 3. Scheduling & Reminders
True temporal awareness and proactive notification systems.
- **Context-Aware Reminders:** Triggers based on state rather than just time (e.g., "Remind me to ask about the API when I open Slack").
- **Cron-Driven Background Tasks:** Schedule recurring workflows (e.g., "Run a daily news summary at 8 AM and send it to my WhatsApp").
- **Interruptible Waiting:** The ability for DIMO to pause a workflow, wait a specific duration, and resume automatically.

## 📧 4. Email & Calendar Integration
Full two-way synchronization with standard productivity suites.
- **Email Triage & Automation:** Secure OAuth integrations (Gmail/Outlook) to read, summarize, draft, and auto-reply to emails based on priority routing.
- **Calendar Management:** Read schedule availability, automatically negotiate meeting times with external contacts via email, and seamlessly inject events into the calendar.
- **Daily Briefings:** An automated morning synthesis combining your calendar events, unread high-priority emails, and pending reminders.

## 🖥️ 5. Local Desktop Automation
Expanding upon the `computer_control` foundations to execute complex local tasks flawlessly.
- **Intelligent GUI Macros:** Record and replay complex UI interactions with self-healing vision parsing (e.g., "Open Photoshop and batch resize these images").
- **File System Orchestration:** Automated background organization of the Downloads folder, semantic searching of local documents, and workspace scaffolding.
- **System Diagnostics:** Deep integration with OS APIs to monitor CPU/RAM, troubleshoot network issues, and fix configuration errors natively.

## 🗣️ 6. Voice Assistant Mode
Making DIMO hands-free and continuously conversational.
- **Wake-Word Detection:** Local, low-power continuous listening for a custom wake-word (e.g., "Hey DIMO").
- **Full-Duplex Conversation:** The ability to interrupt DIMO while it is speaking, allowing for natural, fluid dialogue.
- **Audio-Native Processing:** Direct integration of Whisper (STT) and Piper/ElevenLabs (TTS) into the core LangGraph state, minimizing latency for near-instant responses.

## 📱 7. Mobile Companion
Breaking DIMO out of the desktop environment to follow the user everywhere.
- **Cross-Platform App:** A lightweight React Native or Flutter mobile client that connects securely to the local/cloud DIMO brain.
- **Notification Bridging:** Forwarding desktop notifications to the mobile companion, and vice-versa.
- **Location Awareness:** Using mobile GPS to trigger geo-fenced routines (e.g., "DIMO, turn on my desktop environment when I arrive home").
