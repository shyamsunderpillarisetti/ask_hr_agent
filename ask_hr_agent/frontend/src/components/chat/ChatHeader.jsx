import { Button } from '@/components/ui/button';
import {
  History,
  Plus,
  Headphones
} from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export default function ChatHeader({ user, onToggleHistory, onNewChat, showHistory = true }) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-white/90 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-red-500 to-red-600 flex items-center justify-center shadow-md">
          <span className="text-white font-bold text-lg">M</span>
        </div>
        <div>
          <h1 className="font-semibold text-slate-800 flex items-center gap-2">
            AskHR
            <span className="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded-full">
              Online
            </span>
          </h1>
          <p className="text-xs text-slate-500">Michaels AskHR Agent</p>
        </div>
      </div>
      
      <div className="flex items-center gap-2">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button 
                variant="ghost" 
                size="icon"
                onClick={onToggleHistory}
                disabled={!showHistory}
                className="text-slate-500 hover:text-slate-700 disabled:opacity-40"
              >
                <History className="w-5 h-5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Chat History</TooltipContent>
          </Tooltip>
          
          <Tooltip>
            <TooltipTrigger asChild>
              <Button 
                variant="ghost" 
                size="icon"
                onClick={onNewChat}
                className="text-slate-500 hover:text-slate-700"
              >
                <Plus className="w-5 h-5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>New Conversation</TooltipContent>
          </Tooltip>
          
          <Tooltip>
            <TooltipTrigger asChild>
              <Button 
                variant="ghost" 
                size="icon"
                className="text-slate-500 hover:text-slate-700"
              >
                <Headphones className="w-5 h-5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Contact HR Support</TooltipContent>
          </Tooltip>
        </TooltipProvider>
        
        {user && (
          <div className="ml-2 pl-3 border-l border-slate-200">
            <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center text-sm font-medium text-slate-600">
              {user.full_name?.charAt(0) || 'U'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
