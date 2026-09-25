import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { Ticket, TicketDetail } from '@/types'
import * as ticketsApi from '@/api/tickets'

export const useTicketsStore = defineStore('tickets', () => {
  const tickets = ref<Ticket[]>([])
  const current = ref<TicketDetail | null>(null)
  const loading = ref(false)
  const acting = ref(false)
  const error = ref<string | null>(null)

  const currentTicket = computed(() => current.value?.ticket ?? null)

  function replaceInList(ticket: Ticket): void {
    const index = tickets.value.findIndex((item) => item.id === ticket.id)
    if (index >= 0) tickets.value.splice(index, 1, ticket)
    else tickets.value.unshift(ticket)
  }

  async function loadTickets(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      tickets.value = await ticketsApi.listTickets()
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '加载工单失败'
    } finally {
      loading.value = false
    }
  }

  async function openDetail(ticketId: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      current.value = await ticketsApi.getTicket(ticketId)
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '加载工单详情失败'
    } finally {
      loading.value = false
    }
  }

  function closeDetail(): void {
    current.value = null
  }

  async function createDraft(
    conversationId: string,
    attachmentIds: string[] = [],
  ): Promise<Ticket> {
    acting.value = true
    error.value = null
    try {
      const ticket = await ticketsApi.createDraftFromConversation(conversationId, attachmentIds)
      replaceInList(ticket)
      return ticket
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '创建工单失败'
      throw cause
    } finally {
      acting.value = false
    }
  }

  async function submit(ticketId: string): Promise<Ticket> {
    acting.value = true
    error.value = null
    try {
      const ticket = await ticketsApi.submitTicket(ticketId)
      replaceInList(ticket)
      if (current.value?.ticket.id === ticketId) current.value.ticket = ticket
      return ticket
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '提交工单失败'
      throw cause
    } finally {
      acting.value = false
    }
  }

  async function updateDraft(
    ticketId: string,
    payload: { title?: string; problem_summary?: string },
  ): Promise<Ticket> {
    acting.value = true
    error.value = null
    try {
      const ticket = await ticketsApi.updateTicketDraft(ticketId, payload)
      replaceInList(ticket)
      if (current.value?.ticket.id === ticketId) current.value.ticket = ticket
      return ticket
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '修改工单草稿失败'
      throw cause
    } finally {
      acting.value = false
    }
  }

  async function addMessage(ticketId: string, body: string): Promise<void> {
    acting.value = true
    error.value = null
    try {
      await ticketsApi.addTicketMessage(ticketId, body)
      if (current.value?.ticket.id === ticketId) {
        current.value = await ticketsApi.getTicket(ticketId)
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '发送补充信息失败'
      throw cause
    } finally {
      acting.value = false
    }
  }

  async function confirmResolution(ticketId: string): Promise<Ticket> {
    acting.value = true
    error.value = null
    try {
      const ticket = await ticketsApi.confirmResolution(ticketId)
      replaceInList(ticket)
      if (current.value?.ticket.id === ticketId) current.value.ticket = ticket
      return ticket
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '确认解决失败'
      throw cause
    } finally {
      acting.value = false
    }
  }

  async function reopen(ticketId: string): Promise<Ticket> {
    acting.value = true
    error.value = null
    try {
      const ticket = await ticketsApi.reopenTicket(ticketId)
      replaceInList(ticket)
      if (current.value?.ticket.id === ticketId) {
        current.value.ticket = ticket
        current.value = await ticketsApi.getTicket(ticketId)
      }
      return ticket
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '重开工单失败'
      throw cause
    } finally {
      acting.value = false
    }
  }

  function reset(): void {
    tickets.value = []
    current.value = null
    error.value = null
  }

  return {
    tickets,
    current,
    currentTicket,
    loading,
    acting,
    error,
    loadTickets,
    openDetail,
    closeDetail,
    createDraft,
    updateDraft,
    submit,
    addMessage,
    confirmResolution,
    reopen,
    reset,
  }
})
