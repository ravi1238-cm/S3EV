// Constants
const CHAT_CONFIG = {
    API_URL: window.location.origin,
    BOT_NAME: 'S3 EV Assistant',
    TYPING_DELAY: 300,
    MAX_RETRIES: 3,
    RETRY_DELAY: 1000,
    MAX_MESSAGES: 100,
};

class ChatInterface {
    constructor() {
        this.chatContainer = null;
        this.chatBox = null;
        this.userInput = null;
        this.sendButton = null;
        this.loadingIndicator = null;
        this.chatbotIcon = null;
        this.minimizeButton = null;
        this.messageQueue = [];
        this.isProcessing = false;
        this.isMinimized = true;
        this.hasInitialMessage = false;
        this.messageHistory = [];
        this.boundHandleUserInput = this.handleUserInput.bind(this);
        this.boundToggleChat = this.toggleChat.bind(this);
    }

    initialize() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setup());
        } else {
            this.setup();
        }
    }

    setup() {
        this.setupDOMElements();
        this.createLoadingIndicator();
        this.setupEventListeners();
        this.loadMessageHistory();
        this.toggleChat();
    }

    setupDOMElements() {
        this.chatContainer = document.getElementById("chat-container");
        this.chatBox = document.getElementById("chat-box");
        this.userInput = document.getElementById("user-input");
        this.sendButton = document.getElementById("send-button");
        this.chatbotIcon = document.getElementById("chatbot-icon");
        this.minimizeButton = document.querySelector(".minimize-button");

        if (!this.chatContainer || !this.chatBox || !this.userInput || !this.sendButton || 
            !this.chatbotIcon || !this.minimizeButton) {
            throw new Error("Required DOM elements not found");
        }
    }

    createLoadingIndicator() {
        this.loadingIndicator = document.createElement("div");
        this.loadingIndicator.className = "message bot-message loading-message";
        this.loadingIndicator.innerHTML = `
            <div class="loading-content">
                <div class="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
                <span>${CHAT_CONFIG.BOT_NAME} is thinking...</span>
            </div>
        `;
    }

    setupEventListeners() {
        this.chatbotIcon.addEventListener("click", this.boundToggleChat);
        this.minimizeButton.addEventListener("click", this.boundToggleChat);

        this.userInput.addEventListener("keypress", (event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                this.handleUserInput();
            }
        });

        this.userInput.addEventListener("input", () => this.adjustTextareaHeight());
        this.sendButton.addEventListener("click", this.boundHandleUserInput);
        this.chatBox.addEventListener("scroll", () => this.handleScroll());
        window.addEventListener('resize', () => this.adjustTextareaHeight());
    }

    loadMessageHistory() {
        try {
            const savedMessages = localStorage.getItem('chat-messages');
            if (savedMessages) {
                this.messageHistory = JSON.parse(savedMessages);
                this.messageHistory.forEach(message => this.appendMessage(message, false));
                this.hasInitialMessage = this.messageHistory.some(msg => msg.type === "greeting");
            }
        } catch (error) {
            console.error('Error loading message history:', error);
        }
    }

    saveMessageHistory() {
        try {
            const messagesToSave = this.messageHistory.slice(-CHAT_CONFIG.MAX_MESSAGES);
            localStorage.setItem('chat-messages', JSON.stringify(messagesToSave));
        } catch (error) {
            console.error('Error saving message history:', error);
        }
    }

    adjustTextareaHeight() {
        if (!this.userInput) return;
        this.userInput.style.height = 'auto';
        const maxHeight = 120;
        const scrollHeight = this.userInput.scrollHeight;
        this.userInput.style.height = Math.min(scrollHeight, maxHeight) + 'px';
    }

    toggleChat() {
        this.isMinimized = !this.isMinimized;
        if (this.isMinimized) {
            this.chatContainer.style.display = 'none';
            this.chatbotIcon.style.display = 'flex';
        } else {
            this.chatContainer.style.display = 'flex';
            this.chatbotIcon.style.display = 'none';

            if (!this.hasInitialMessage) {
                this.appendMessage({
                    text: `Welcome! How may I assist you today?`,
                    sender: "bot",
                    type: "greeting"
                });
                this.hasInitialMessage = true;
            }
            this.userInput.focus();
        }
    }

    async handleUserInput() {
        const message = this.userInput.value.trim();
        if (!message || this.isProcessing) return;

        try {
            this.setInputState(false);
            this.appendMessage({
                text: message,
                sender: "user"
            });
            this.userInput.value = "";
            this.adjustTextareaHeight();
            this.showLoadingIndicator();
            await this.processMessage(message);
        } catch (error) {
            this.handleError(error);
        } finally {
            this.setInputState(true);
            this.hideLoadingIndicator();
        }
    }

    showLoadingIndicator() {
        this.chatBox.appendChild(this.loadingIndicator);
        this.scrollToBottom();
    }

    hideLoadingIndicator() {
        if (this.loadingIndicator.parentNode === this.chatBox) {
            this.chatBox.removeChild(this.loadingIndicator);
        }
    }

    async processMessage(message) {
        try {
            const response = await this.sendMessageToServer(message);
            await this.handleServerResponse(response);
        } catch (error) {
            this.handleError(error);
        }
    }

    async sendMessageToServer(message) {
        const response = await fetch(`${CHAT_CONFIG.API_URL}/ask/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: message })
        });

        if (!response.ok) throw new Error(`Server error: ${response.status}`);
        return response;
    }

    async handleServerResponse(response) {
        const botMessageDiv = this.appendMessage({
            text: "",
            sender: "bot",
            isStreaming: true
        });

        const botContent = botMessageDiv.querySelector("span") || botMessageDiv;
        let responseText = "";
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        try {
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value);
                responseText += chunk;
                botContent.textContent = responseText;
                this.scrollToBottom();
            }
        } finally {
            reader.releaseLock();
        }
        
        this.hideLoadingIndicator();
    }

    appendMessage({ text, sender }, saveToHistory = true) {
        const messageDiv = document.createElement("div");
        messageDiv.classList.add("message", `${sender}-message`);
        messageDiv.textContent = `${sender === "user" ? "You" : CHAT_CONFIG.BOT_NAME}: ${text}`;

        this.chatBox.appendChild(messageDiv);
        this.scrollToBottom();

        if (saveToHistory) {
            this.messageHistory.push({ text, sender });
            this.saveMessageHistory();
        }

        return messageDiv;
    }

    setInputState(enabled) {
        this.userInput.disabled = !enabled;
        this.sendButton.disabled = !enabled;
        if (enabled) this.userInput.focus();
    }

    scrollToBottom() {
        this.chatBox.scrollTop = this.chatBox.scrollHeight;
    }
}

// Initialize chat interface
const chatInterface = new ChatInterface();
chatInterface.initialize();

// Export for external use
window.chatInterface = chatInterface;
