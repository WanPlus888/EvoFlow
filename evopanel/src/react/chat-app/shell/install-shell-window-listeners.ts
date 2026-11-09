// @ts-nocheck — mechanical extract.
/**
 * Shell window custom-event listeners. Extracted (P87).
 */
import { applyPendingOpsBotDraft } from './apply-pending-ops-bot-draft.js'

export type RunShellWindowListenersEffectCtx = Record<string, any>

export function runShellWindowListenersEffect(ctx: RunShellWindowListenersEffectCtx): void | (() => void) {
  const {
    cancelPendingStreamUiBumpsRef,
    handleNewSessionRef,
    handleOpenHomeRef,
    isChatOverlayDeferActive,
    openCollabExecPanel,
    preferHomeDashboardRef,
    pushComposerText,
    reviveAllTurnBusyIfLivePostOpen,
    scheduleBumpRef,
    selectSessionFromShellRef,
    sessionRef,
    setChatSurfaceVisible,
    setMobileChatPane,
    setPreferHomeDashboard,
  } = ctx
    const onNew = () => {
      if (typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches) {
        setMobileChatPane('thread')
      }
      void handleNewSessionRef.current?.()
    }
    const onOpenHome = () => {
      if (typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches) {
        setMobileChatPane('list')
        return
      }
      void handleOpenHomeRef.current?.()
    }
    const onMobileChatList = () => {
      setMobileChatPane('list')
    }
    const onSettingsModalOpened = () => {
      cancelPendingStreamUiBumpsRef.current()
    }
    const onSettingsModalClosed = () => {
      if (!isChatOverlayDeferActive()) {
        scheduleBumpRef.current?.({ immediate: true })
      }
    }
    const onChatRouteShown = () => {
      // 从知识库/菜单返回：强制解开消息面 + 确保常驻宿主可见
      setChatSurfaceVisible(true)
      try {
        const host = document.getElementById('chat-persistent-host')
        if (host) {
          host.hidden = false
          host.style.display = 'flex'
        }
      } catch {
        /* ignore */
      }
      try {
        const pending = sessionStorage.getItem('evopanel_pending_shell_session')
        const pendingTaskId = sessionStorage.getItem('evopanel_pending_shell_task_id')
        const pendingThread = sessionStorage.getItem('evopanel_pending_shell_thread')
        const pendingOpenWorkflow =
          sessionStorage.getItem('evopanel_pending_open_collab_workflow') === '1'
        let pendingSubtask: Record<string, string> | null = null
        try {
          const raw = sessionStorage.getItem('evopanel_pending_collab_subtask')
          if (raw) pendingSubtask = JSON.parse(raw)
        } catch {
          pendingSubtask = null
        }
        if (pending) {
          sessionStorage.removeItem('evopanel_pending_shell_session')
          selectSessionFromShellRef.current(pending)
        }
        // ChatApp 已挂载时 mount effect 不会重跑：在此补开工作流 + 节点进度 tab
        if (pendingOpenWorkflow || pendingSubtask?.subtaskId) {
          sessionStorage.removeItem('evopanel_pending_open_collab_workflow')
          sessionStorage.removeItem('evopanel_pending_collab_subtask')
          try {
            openCollabExecPanel?.({ clearDismiss: true })
          } catch {
            /* ignore */
          }
          if (pendingSubtask?.subtaskId) {
            window.setTimeout(() => {
              void import('../../../lib/right-stage/open-collab-subtask-stage.js').then((m) => {
                m.openCollabSubtaskInRightStage(
                  {
                    subtaskId: String(pendingSubtask?.subtaskId || ''),
                    mainTaskId: String(pendingSubtask?.mainTaskId || pendingTaskId || ''),
                    leadThreadId: String(pendingSubtask?.leadThreadId || pendingThread || ''),
                    title: String(pendingSubtask?.title || ''),
                    status: String(pendingSubtask?.status || ''),
                    assignedAgent: String(pendingSubtask?.assignedAgent || ''),
                  },
                  { sessionKey: pending || undefined },
                )
              })
            }, 80)
          }
        }
        if (sessionStorage.getItem('evopanel_pending_mobile_chat_list') === '1') {
          sessionStorage.removeItem('evopanel_pending_mobile_chat_list')
          setMobileChatPane('list')
        }
      } catch {
        /* ignore */
      }
      // 1.4.10 运营大脑 bot 预填（P0-3）：已挂载时在此消费 pending 草稿；
      // 只写输入框（applyPendingOpsBotDraft 内无任何发送/计费/建单链路）
      try {
        applyPendingOpsBotDraft(pushComposerText)
      } catch {
        /* ignore */
      }
      // 任务中心等路由回来：恢复所有 live POST 仍开着却被误 idle 的会话
      reviveAllTurnBusyIfLivePostOpen()
    }
    const onShellSelectSession = (ev: Event) => {
      const key = String((ev as CustomEvent<{ sessionKey?: string }>).detail?.sessionKey || '').trim()
      if (!key) return
      selectSessionFromShellRef.current(key)
    }
    /**
     * 1.4.16 运营大脑回程（侧栏「运营大脑」→ shell-aside 派发）：
     * reenterOpsBotMode 只切 bot 表现态；已在 /chat 且 preferHomeDashboard=true 时
     * 主区仍挂 EvoFlowHomeDashboard（驾驶舱首页），必须在此清首页意图并尽量回到
     * 上一会话（handleOpenHome 记的 ef-ops-bot-last-session），兜底空白聊天草稿。
     */
    const onOpsBrainReenter = () => {
      // 1) 先同步清「驾驶舱首页」意图（ref 先行，防 refresh 把空选中当首页回填）
      if (preferHomeDashboardRef) preferHomeDashboardRef.current = false
      setPreferHomeDashboard?.(false)
      // 2) 有上一会话 → 回它（selectSessionFromShell 会再清一次 preferHome 并落 sessionKey）
      let lastSession = ''
      try {
        lastSession = String(sessionStorage.getItem('ef-ops-bot-last-session') || '').trim()
      } catch {
        lastSession = ''
      }
      if (lastSession) {
        selectSessionFromShellRef.current(lastSession)
        return
      }
      // 3) 无记录但已在某会话上 → 只清 preferHome 即可；4) 全空 → 空白聊天草稿（绝不回驾驶舱）
      if (String(sessionRef?.current || '').trim()) return
      void handleNewSessionRef.current?.()
    }
    window.addEventListener('evopanel:shell-new-session', onNew)
    window.addEventListener('evopanel:shell-open-home', onOpenHome)
    window.addEventListener('evopanel:mobile-chat-list', onMobileChatList)
    window.addEventListener('evopanel:shell-select-session', onShellSelectSession)
    window.addEventListener('evopanel:settings-modal-opened', onSettingsModalOpened)
    window.addEventListener('evopanel:settings-modal-closed', onSettingsModalClosed)
    window.addEventListener('evopanel:chat-route-shown', onChatRouteShown)
    window.addEventListener('evopanel:ops-brain-reenter', onOpsBrainReenter)
    return () => {
      window.removeEventListener('evopanel:shell-new-session', onNew)
      window.removeEventListener('evopanel:shell-open-home', onOpenHome)
      window.removeEventListener('evopanel:mobile-chat-list', onMobileChatList)
      window.removeEventListener('evopanel:shell-select-session', onShellSelectSession)
      window.removeEventListener('evopanel:settings-modal-opened', onSettingsModalOpened)
      window.removeEventListener('evopanel:settings-modal-closed', onSettingsModalClosed)
      window.removeEventListener('evopanel:chat-route-shown', onChatRouteShown)
      window.removeEventListener('evopanel:ops-brain-reenter', onOpsBrainReenter)
    }
}
