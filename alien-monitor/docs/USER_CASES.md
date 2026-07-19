# Alien Monitor — User Cases

## 1. Developer Debugging

**Who:** Smart contract developer debugging a payment channel issue.

**Scenario:**
1. Launch monitor in LIVE mode connected to testnet
2. Observe EVM Escrow node — see channel count and TVL
3. Click the node to see metrics and status
4. Watch Transaction Flow for channel_open/channel_close events
5. Notice a spike of failed channel_close attempts → investigate
6. Use AI Assistant: "Why would a channel close fail on EVM escrow?"

**Value:** Instant visual identification of anomalies without grep'ing logs.

---

## 2. DevOps Monitoring

**Who:** Platform engineer responsible for ecosystem uptime.

**Scenario:**
1. Monitor running in LIVE mode on a wall display
2. All 17 nodes show green status dots → everything healthy
3. AI-Factory node turns yellow → tasks_pending spikes to 50
4. Click node → details show task queue is backing up
5. Drill into plugins → see which plugin is bottlenecked
6. Correlate with Prometheus metrics in the summary bar

**Value:** Single pane of glass for the entire distributed system.

---

## 3. Investor Demo

**Who:** Founder presenting to VCs.

**Scenario:**
1. Launch in TEST mode with PULSE at 100%, Magenta theme
2. "This is our ecosystem — alive, breathing, transacting"
3. Zoom into the central hub — show the corona, the orbiting services
4. Click through nodes: "8 desktop apps online, $12K volume today"
5. Toggle to LIVE mode: "And here's the real thing"
6. AI Assistant answers investor's question about scalability

**Value:** Makes abstract infrastructure tangible. Creates "wow" moment.

---

## 4. New Developer Onboarding

**Who:** Junior developer joining the AIMarket team.

**Scenario:**
1. Launch monitor in TEST mode
2. Explore the 3D graph — visually understand component relationships
3. Click each node to read its description and see its API endpoints
4. Use AI Assistant: "What is the difference between EVM and Solana escrow?"
5. Watch Transaction Flow to understand the payment lifecycle
6. Read Node Inspector → click Plugins → see all 15 sub-components

**Value:** Learn the architecture in 10 minutes instead of reading 100 pages of docs.

---

## 5. Integration Testing

**Who:** QA engineer testing a new desktop app integration.

**Scenario:**
1. Start full stack: `./start.sh --with-infra`
2. Launch the desktop app (e.g., Capability Composer)
3. In monitor: Desktop Apps node shows "2 online" → confirm app connected
4. Use the app to invoke a capability
5. In monitor: Transaction Flow shows the invoke → "hub" with amount
6. Channel opens, payment flows, verify all in real-time
7. AI Assistant: "What plugins fire during invoke?"

**Value:** End-to-end visibility into integration test outcomes.

---

## 6. Security Audit

**Who:** Security researcher evaluating the payment channel architecture.

**Scenario:**
1. Monitor in LIVE mode
2. Focus on EVM Escrow and Solana Escrow nodes
3. Watch Transaction Flow for unusual patterns (large amounts, rapid channel cycling)
4. Click Plugins → Safety Gate → check if pre-invoke checks are active
5. Plugins → TEE Attestation → verify attestation status
6. AI Assistant: "How does the safety gate plugin validate invocations?"

**Value:** Visual pattern recognition for security anomalies.

---

## 7. Performance Tuning

**Who:** Backend engineer optimizing hub throughput.

**Scenario:**
1. Monitor shows invocations_24h metric in the top bar
2. Observe the rate — currently 350/hour
3. Run a load test against the hub
4. Watch invocations_24h climb in real-time
5. Hub node pulses faster — visual indicator of load
6. Check if channels_open keeps pace with invocations
7. AI Assistant: "What's the channel lifecycle bottleneck?"

**Value:** Real-time feedback loop for performance experiments.

---

## 8. Federation Health Check

**Who:** Protocol designer verifying cross-hub federation.

**Scenario:**
1. LIVE mode showing Federation node
2. Click node → see peer count and crawl stats
3. If peers < 3 → investigate network connectivity
4. Trigger a crawl → watch for new peers appearing
5. Check Reputation Dashboard (desktop app) for trust scores
6. AI Assistant: "How does BFS peer discovery work?"

**Value:** Monitor the health of the federated network topology.

---

## 9. Plugin Development

**Who:** Plugin developer testing a new plugin.

**Scenario:**
1. Launch monitor, note Plugins node shows "12/15 loaded"
2. Install the new plugin, restart hub
3. Monitor now shows "13/15 loaded" — instant confirmation
4. Click Plugins → new plugin appears in sub-components list
5. Invoke a capability that triggers the plugin
6. Transaction Flow shows the invoke passing through the plugin hook
7. AI Assistant: "What hooks does a plugin need to implement?"

**Value:** Instant feedback on plugin registration and execution.

---

## 10. Cross-Team Alignment

**Who:** Product manager presenting quarterly roadmap.

**Scenario:**
1. Monitor on big screen during all-hands
2. "Here's where we are today" — show current ecosystem state
3. "Here's what we're adding" — point to where new components will appear
4. "And this is the volume we're targeting" — point to metrics bar
5. Toggle between TEST (aspirational state) and LIVE (current reality)
6. AI Assistant answers team questions about technical capabilities

**Value:** Shared mental model of the system across technical and non-technical stakeholders.
