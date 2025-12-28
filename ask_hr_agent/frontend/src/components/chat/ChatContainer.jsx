import { useCallback, useEffect, useState } from 'react';
import { ChatSession, Message } from '@/api/entities';
import config from '@/config';
import ChatHeader from './ChatHeader';
import MessageList from './MessageList';
import MessageInput from './MessageInput';
import HistoryPanel from './HistoryPanel';
import VoiceInput from './VoiceInput';
import { Loader2 } from 'lucide-react';

export default function ChatContainer({ user }) {
  const [ragConversation, setRagConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [conversations, setConversations] = useState([]);
  const [error, setError] = useState(null);

  const initializeChat = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);

      // Add a timeout to prevent infinite loading if the backend is down
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error('Request timed out')), 10000)
      );

      const chatPromise = ChatSession.create({
        agent_name: config.agentName,
        name: `HR Chat - ${new Date().toLocaleDateString()}`,
        user_name: user?.full_name || 'Employee'
      });

      const newConversation = await Promise.race([chatPromise, timeoutPromise]);
      
      setRagConversation(newConversation);
      const welcomeMessage = "Hello! I'm the AskHR agent for Michaels.";
      setMessages([{
        id: 'welcome-' + Date.now(),
        role: 'assistant',
        content: welcomeMessage,
        created_at: new Date().toISOString()
      }]);
    } catch (error) {
      setError('Failed to initialize chat. Please check your connection or try again later.');
      console.error('Chat init error:', error);
      // Ensure loading state is cleared even on error so user sees the error message
    } finally {
      setIsLoading(false);
    }
  }, [user?.full_name]);

  const loadConversationHistory = useCallback(async () => {
    try {
      // Using filter instead of list to filter by agent_name if supported, otherwise just list
      const history = await ChatSession.list('-created_at', 50);
      setConversations(history || []);
    } catch (error) {
      console.error('Failed to load history:', error);
    }
  }, []);

  const loadConversation = useCallback(async (conversationId) => {
    try {
      setIsLoading(true);
      const conv = await ChatSession.get(conversationId);
      setRagConversation(conv);
      // Fetch messages for this conversation
      const msgs = await Message.list('created_at', 100, 0, { chat_session_id: conversationId });
      setMessages(msgs || []);
      setShowHistory(false);
    } catch (error) {
      setError('Failed to load conversation.');
      console.error('Failed to load conversation:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Initialize or load conversation
  useEffect(() => {
    initializeChat();
    loadConversationHistory();
  }, [initializeChat, loadConversationHistory]);

  const sendMessage = async (text, fileUrls = []) => {
    if (!text.trim() && fileUrls.length === 0) {
      return;
    }
    
    setIsTyping(true);
    setError(null);
    
    try {
      // Add user message to UI immediately
      const tempMsgId = 'temp-' + Date.now();
      const userMsg = {
        id: tempMsgId,
        role: 'user',
        content: text,
        created_at: new Date().toISOString()
      };
      
      setMessages(prev => [...prev, userMsg]);

      let currentConversation = ragConversation;
      if (!currentConversation) {
        try {
          setIsLoading(true);
          currentConversation = await ChatSession.create({
            agent_name: config.agentName,
            name: `HR Chat - ${new Date().toLocaleDateString()}`,
            user_name: user?.full_name || 'Employee',
            initial_message: text // Optional: backend might use this to start context
          });
          setRagConversation(currentConversation);
        } catch (error) {
          setError('Failed to start conversation. Please try again.');
          console.error('Failed to start conversation:', error);
          setIsTyping(false);
          setIsLoading(false);
          return;
        }
      }

      const response = await Message.create({
        chat_session_id: currentConversation.id,
        content: text,
        file_urls: fileUrls
      });

      const aiMsg = {
        id: response.id || 'ai-' + Date.now(),
        role: 'assistant',
        content: response.content || response.response || response.reply || response.answer || response.reply_text || "I received your message but couldn't process the response.",
        created_at: response.created_at || new Date().toISOString(),
        citations: response.citations || [] // Store citations if available
      };

      setMessages(prev => [...prev, aiMsg]);
      setIsTyping(false);
      setIsLoading(false);
      
    } catch (error) {
      setError('Failed to send message. Please try again.');
      setIsTyping(false);
      setIsLoading(false);
      console.error(error);
    }
  };

  // If user sends a message that doesn't match a quick action, 
  // we treat it as a general query (which includes "My Benefits" if user typed it or similar context)
  // The backend RAG should handle the "My Benefits" context logic based on the query "Tell me about my benefits."


  const handleFeedback = async (messageId, feedback) => {
    try {
      await Message.update(messageId, { feedback });
    } catch (err) {
      console.error('Failed to save feedback:', err);
    }
  };

  if (isLoading && !ragConversation && !error) {
    return (
      <div className="flex items-center justify-center h-full bg-gradient-to-br from-slate-50 to-slate-100">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin text-red-600 mx-auto mb-3" />
          <p className="text-slate-600">Starting your HR session...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full bg-gradient-to-br from-slate-50 via-white to-slate-50">
      {/* History Panel */}
      <HistoryPanel 
        isOpen={showHistory}
        conversations={conversations}
        currentId={ragConversation?.id}
        onSelect={loadConversation}
        onClose={() => setShowHistory(false)}
        onNewChat={initializeChat}
      />
      
      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col h-full max-w-4xl mx-auto w-full">
        <ChatHeader 
          user={user}
          onToggleHistory={() => setShowHistory(!showHistory)}
          onNewChat={initializeChat}
        />
        
        {/* Messages Area */}
        <div className="flex-1 overflow-hidden relative">
          <MessageList 
            messages={messages} 
            isTyping={isTyping}
            onFeedback={handleFeedback}
          />
        </div>
        
        {/* Error Banner */}
        {error && (
          <div className="mx-4 mb-2 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        )}
        
        {/* Input Area */}
        <div className="p-4 border-t border-slate-200 bg-white/80 backdrop-blur-sm">
          <div className="flex items-end gap-2 mb-2">
            <MessageInput 
              onSend={sendMessage} 
              disabled={isTyping || isLoading}
              placeholder="Ask me about HR policies, leave, benefits..."
            />
            <VoiceInput 
              onTranscript={sendMessage}
              disabled={isTyping || isLoading}
            />
          </div>
          
        </div>
      </div>
    </div>
  );
}
