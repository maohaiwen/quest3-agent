// Execution event handler for Plan and ReAct modes

// Agent management
let agents = [];
let currentAgentId = null;

// Load agents
async function loadAgents() {
    try {
        const response = await fetch('/api/agents?enabled_only=true');
        const data = await response.json();
        agents = data.agents || [];
        updateAgentSelector();
    } catch (error) {
        console.error('Error loading agents:', error);
    }
}

// Update agent selector
function updateAgentSelector() {
    const selector = document.getElementById('agentSelector');
    if (!selector) return;

    // Save current selection
    const currentValue = selector.value;

    // Clear options except default
    while (selector.options.length > 1) {
        selector.remove(1);
    }

    // Add agent options
    agents.forEach(agent => {
        const option = document.createElement('option');
        option.value = agent.id;
        option.textContent = `${agent.name} (${agent.type})`;
        option.dataset.mode = agent.execution_mode || 'plan';
        option.dataset.type = agent.type;
        selector.appendChild(option);
    });

    // Restore selection if still valid
    if (currentValue && (currentValue === '' || agents.some(a => a.id === currentValue))) {
        selector.value = currentValue;
    }
}

// Show active agent info
function showActiveAgent(agent) {
    const agentInfo = document.querySelector('.active-agent-info');

    if (!agentInfo) {
        agentInfo = document.createElement('div');
        agentInfo.className = 'active-agent-info';
        const chatPanel = document.querySelector('.chat-panel');
        if (chatPanel) {
            chatPanel.insertBefore(agentInfo, chatPanel.firstChild);
        }
    }

    const modeIcon = agent.execution_mode === 'react' ? '🔄' : (agent.execution_mode === 'direct' ? '⚡' : '📋');

    agentInfo.innerHTML = `
        <span class="agent-icon">${modeIcon}</span>
        <span class="agent-name">${agent.name}</span>
        <span class="agent-type">(${agent.type})</span>
        <span class="agent-mode">[${agent.execution_mode || 'plan'}]</span>
    `;
}

function showDefaultAgent() {
    const agentInfo = document.querySelector('.active-agent-info');
    if (agentInfo) {
        agentInfo.innerHTML = '使用默认Agent（自动选择）';
    }
}

// Agent selection change
document.addEventListener('DOMContentLoaded', () => {
    const selector = document.getElementById('agentSelector');
    if (selector) {
        selector.addEventListener('change',', (e) => {
            currentAgentId = e.target.value;
            log(`Agent selected: ${currentAgentId || 'default'}`);

            // Reconnect with selected agent if connected
            if (ws && ws.readyState === WebSocket.OPEN) {
                // Send agent update
                ws.send(JSON.stringify({
                    agent_id: currentAgentId
                }));
            }
        });
    }

    // Load agents on page load
    loadAgents();
});

// Execution event handlers
function handlePlanningEvent(plan) {
    const messagesDiv = document.getElementById('messages');
    if (!messagesDiv) return;

    const planCard = document.createElement('div');
    planCard.className = 'planning-card';
    planCard.innerHTML = `
        <div class="planning-header">📋 执行计划</div>
        <div class="planning-body">
            <div class="planning-item">
                <span class="planning-label">复杂度:</span>
                <span class="planning-value complexity-${(plan.complexity || '').toLowerCase()}">${plan.complexity || 'UNKNOWN'}</span>
            </div>
            <div class="planning-item">
                <span class="planning-label">策略:</span>
                <span class="planning-value">${plan.strategy || 'unknown'}</span>
            </div>
            <div class="planning-item">
                <span class="planning-label">描述:</span>
                <span class="planning-value">${plan.description || ''}</span>
            </div>
            <div class="planning-item">
                <span class="planning-label">步骤数:</span>
                <span class="planning-value">${plan.step_count || 0}</span>
            </div>
        </div>
    `;

    // Insert before typing indicator
    const typingIndicator = document.getElementById('typingIndicator');
    messagesDiv.insertBefore(planCard, typingIndicator);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function handleStepStartEvent(step) {
    const messagesDiv = document.getElementById('messages');
    if (!messagesDiv) return;

    const stepDiv = document.createElement('div');
    stepDiv.className = 'execution-step';
    stepDiv.id = `step-${step.step_id}`;

    stepDiv.innerHTML = `
        <div class="step-header">
            <span class="step-number">步骤 ${step.step_number}/${step.total_steps}</span>
            <span class="step-name">${step.tool_name || step.tool_name}</span>
            <span class="step-status running" id="status-${step.step_id}">⏳ 执行中...</span>
        </div>
    `;

    // Insert before typing indicator
    const typingIndicator = document.getElementById('typingIndicator');
    messagesDiv.insertBefore(stepDiv, typingIndicator);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function handleStepProgressEvent(stepId, message) {
    const statusEl = document.getElementById(`status-${stepId}`);
    if (statusEl) {
        statusEl.textContent = message;
    }
}

function handleStepCompleteEvent(stepId, result) {
    const statusEl = document.getElementById(`status-${stepId}`);
    if (statusEl) {
        statusEl.className = 'step-status complete';
        statusEl.textContent = '✅ 完成';
    }

    const stepDiv = document.getElementById(`step-${stepId}`);
    if (stepDiv) {
        // Check if this is a thinking step (virtual step without real tool call)
        const isThinkingStep = result && typeof result === 'object' && result.type === 'thinking_step';

        if (!isThinkingStep && result) {
            // Only show result for real tool execution steps
            const resultDiv = document.createElement('div');
            resultDiv.className = 'step-result';

            const resultContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);

            resultDiv.innerHTML = `
                <div class="step-result-label">结果: <small>(预览)</small></div>
                <div class="step-result-content">${escapeHtml(resultContent)}</div>
            `;

            stepDiv.appendChild(resultDiv);
        }
    }

    // Scroll to bottom
    const messagesDiv = document.getElementById('messages');
    if (messagesDiv) {
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }
}

function handleStepErrorEvent(stepId, error) {
    const statusEl = document.getElementById(`status-${stepId}`);
    if (statusEl) {
        statusEl.className = 'step-status error';
        statusEl.textContent = '❌ 失败';
    }

    const stepDiv = document.getElementById(`step-${stepId}`);
    if (stepDiv) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'step-error';
        errorDiv.textContent = error;
        stepDiv.appendChild(errorDiv);
    }

    // Scroll to bottom
    const messagesDiv = document.getElementById('messages');
    if (messagesDiv) {
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }
}

// ReAct mode handlers
function handlePhaseEvent(phaseData) {
    // Update current phase display if needed
    console.log(`Phase: ${phaseData.phase}, Step: ${phaseData.step}/${phaseData.total_steps}`);
}

function handleThoughtEvent(thought) {
    // ReAct thinking
    const messagesDiv = document.getElementById('messages');
    if (!messagesDiv) return;

    const thinkingDiv = document.createElement('div');
    thinkingDiv.className = 'react-step';
    thinkingDiv.innerHTML = `
        <div class="react-step-header">
            <span class="react-step-number">#</span>
            <span class="react-phase">思考中...</span>
        </div>
        <div class="react-content">${escapeHtml(thought)}</div>
    `;

    // Insert before typing indicator
    const typingIndicator = document.getElementById('typingIndicator');
    messagesDiv.insertBefore(thinkingDiv, typingIndicator);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function handleActionStartEvent(actionData) {
    const messagesDiv = document.getElementById('messages');
    if (!messagesDiv) return;

    const actionDiv = document.createElement('div');
    actionDiv.className = 'react-step';
    actionDiv.id = `react-step-${actionData.step}`;

    const paramsText = Object.keys(actionData.arguments || {}).length > 0
        ? JSON.stringify(actionData.arguments, null, 2)
        : '(无参数)';

    actionDiv.innerHTML = `
        <div class="react-step-header">
            <span class="react-step-number">#${actionData.step}</span>
            <span class="react-phase">行动</span>
        </div>
        ${actionData.thought ? `
            <div class="react-content" style="margin-bottom: 10px;">
                <small style="color: #999;">思考:</small><br>
                ${escapeHtml(actionData.thought)}
            </div>
        ` : ''}
        <div class="react-action">
            <div class="react-action-header">🔧 调用工具: ${actionData.tool_name}</div>
            <div style="margin-top: 5px;">
                <small style="color: #999;">参数:</small><br>
                <code style="background: #f8f9fa; padding: 5px; border-radius: 4px; font-size: 12px;">${escapeHtml(paramsText)}</code>
            </div>
        </div>
    `;

    // Insert before typing indicator
    const typingIndicator = document.getElementById('typingIndicator');
    messagesDiv.insertBefore(actionDiv, typingIndicator);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function handleObservationEvent(obsData) {
    const messagesDiv = document.getElementById('messages');
    if (!messagesDiv) return;

    const obsDiv = document.createElement('div');
    obsDiv.className = 'react-observation';

    const resultContent = typeof obsData.result === 'string'
        ? obsData.result
        : JSON.stringify(obsData.result, null, 2);

    obsDiv.innerHTML = `
        <div class="react-observation-header">👁 观察结果: ${escapeHtml(obsData.tool_name || '')}</div>
        <div class="react-observation-content">${escapeHtml(resultContent)}</div>
    `;

    // Append to the last react step
    const lastReactStep = document.getElementById(`react-step-${obsData.step}`);
    if (lastReactStep) {
        lastReactStep.appendChild(obsDiv);
    } else {
        // Fallback: insert before typing indicator
        const typingIndicator = document.getElementById('typingIndicator');
        messagesDiv.insertBefore(obsDiv, typingIndicator);
    }

    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function handleCompleteEvent(data) {
    // Task completed
    console.log('Task completed:', data);
}

function handleTerminatedEvent(data) {
    // Execution terminated early
    const messagesDiv = document.getElementById('messages');
    if (!messagesDiv) return;

    const termDiv = document.createElement('div');
    termDiv.className = 'execution-phase';
    termDiv.innerHTML = `
        <div class="phase-content">⚠️ 执行终止: ${data.reason || '未知原因'}</div>
    `;

    const typingIndicator = document.getElementById('typingIndicator');
    messagesDiv.insertBefore(termDiv, typingIndicator);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function handleInfoEvent(data) {
    console.log('Info:', data.message);
}

// Utility function
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
