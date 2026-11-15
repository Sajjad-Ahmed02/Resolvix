import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthContext } from "../context/authContext";
import Chat from "./Chat";
import * as conversationService from "../services/conversationService";

vi.mock("../services/conversationService", () => ({
  listConversations: vi.fn(),
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  listMessages: vi.fn(),
  sendMessage: vi.fn(),
}));

const conversation = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Delivery question",
  created_at: "2026-11-15T10:00:00Z",
  updated_at: "2026-11-15T10:05:00Z",
};

const secondConversation = {
  id: "22222222-2222-4222-8222-222222222222",
  title: "Refund request",
  created_at: "2026-11-14T09:00:00Z",
  updated_at: "2026-11-14T09:15:00Z",
};

function renderChat(overrides = {}) {
  const auth = {
    user: {
      id: "user-1",
      name: "Alice Morgan",
      email: "alice.morgan@example.com",
      role: "customer",
    },
    isAuthenticated: true,
    isInitializing: false,
    notice: "",
    signIn: vi.fn(),
    signOut: vi.fn(),
    clearNotice: vi.fn(),
    ...overrides,
  };

  return render(
    <AuthContext.Provider value={auth}>
      <Chat />
    </AuthContext.Provider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.resetAllMocks();
  conversationService.listConversations.mockResolvedValue([]);
  conversationService.listMessages.mockResolvedValue([]);
});

describe("Chat", () => {
  it("shows a loading state while conversations are fetched", async () => {
    let resolveConversations;

    conversationService.listConversations.mockReturnValue(
      new Promise((resolve) => {
        resolveConversations = resolve;
      }),
    );

    renderChat();

    expect(screen.getByText("Loading conversations…")).toBeInTheDocument();

    await act(async () => {
      resolveConversations([]);
    });

    expect(
      await screen.findByRole("heading", { name: "Start a conversation" }),
    ).toBeInTheDocument();
  });

  it("shows the empty state when the customer has no conversations", async () => {
    renderChat();

    expect(await screen.findByText("No conversations yet")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Start your first conversation",
      }),
    ).toBeEnabled();
  });

  it("loads the selected conversation history after a refresh", async () => {
    window.localStorage.setItem(
      "resolvix.chat.lastConversation",
      JSON.stringify(secondConversation.id),
    );
    conversationService.listConversations.mockResolvedValue([
      conversation,
      secondConversation,
    ]);
    conversationService.listMessages.mockResolvedValue([
      {
        id: "message-1",
        role: "user",
        content: "Where is my refund?",
        metadata: null,
        created_at: "2026-11-14T09:10:00Z",
      },
      {
        id: "message-2",
        role: "assistant",
        content: "Your refund is being reviewed.",
        metadata: null,
        created_at: "2026-11-14T09:11:00Z",
      },
    ]);

    renderChat();

    expect(
      await screen.findByText("Where is my refund?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Your refund is being reviewed."),
    ).toBeInTheDocument();
    expect(conversationService.listMessages).toHaveBeenCalledWith(
      secondConversation.id,
    );
  });

  it("shows an error notification when loading conversations fails", async () => {
    conversationService.listConversations.mockRejectedValue({
      response: { data: { detail: "The database is unavailable." } },
    });

    renderChat();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The database is unavailable.",
    );
  });

  it("creates a conversation and enables the composer", async () => {
    const created = {
      id: "33333333-3333-4333-8333-333333333333",
      title: null,
      created_at: "2026-11-15T11:00:00Z",
      updated_at: "2026-11-15T11:00:00Z",
    };
    conversationService.createConversation.mockResolvedValue(created);

    renderChat();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Start your first conversation",
      }),
    );

    expect(conversationService.createConversation).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("No messages yet")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeEnabled();
    expect(conversationService.listMessages).not.toHaveBeenCalled();
  });

  it("shows an error and keeps the draft when sending fails", async () => {
    conversationService.listConversations.mockResolvedValue([conversation]);
    conversationService.sendMessage.mockRejectedValue({
      response: { data: { detail: "The message could not be saved." } },
    });

    renderChat();

    const input = await screen.findByRole("textbox", { name: "Message" });
    await waitFor(() => expect(input).toBeEnabled());

    fireEvent.change(input, { target: { value: "Please keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The message could not be saved.",
    );
    expect(input).toHaveValue("Please keep this draft");
    expect(conversationService.sendMessage).toHaveBeenCalledTimes(1);
  });

  it("prevents duplicate submissions while a message is being sent", async () => {
    conversationService.listConversations.mockResolvedValue([conversation]);

    let resolveSend;
    conversationService.sendMessage.mockReturnValue(
      new Promise((resolve) => {
        resolveSend = resolve;
      }),
    );

    renderChat();

    const input = await screen.findByRole("textbox", { name: "Message" });
    await waitFor(() => expect(input).toBeEnabled());

    fireEvent.change(input, { target: { value: "  Where is my order?  " } });

    const sendButton = screen.getByRole("button", { name: "Send message" });
    fireEvent.click(sendButton);
    fireEvent.click(sendButton);

    expect(conversationService.sendMessage).toHaveBeenCalledTimes(1);
    expect(conversationService.sendMessage).toHaveBeenCalledWith(
      conversation.id,
      "Where is my order?",
    );
    expect(
      screen.getByRole("button", { name: "Sending message" }),
    ).toBeDisabled();
    expect(
      screen.getByLabelText("Resolvix is preparing a reply"),
    ).toBeInTheDocument();

    await act(async () => {
      resolveSend({
        conversation: {
          ...conversation,
          title: "Where is my order?",
          updated_at: "2026-11-15T10:10:00Z",
        },
        user_message: {
          id: "message-user",
          role: "user",
          content: "Where is my order?",
          metadata: null,
          created_at: "2026-11-15T10:10:00Z",
        },
        assistant_message: {
          id: "message-assistant",
          role: "assistant",
          content: "Your order is on the way.",
          metadata: {
            source: "llm",
            provider: "gemini",
            model: "gemini-3.5-flash-lite",
          },
          created_at: "2026-11-15T10:10:01Z",
        },
      });
    });

    const messageLog = await screen.findByRole("log");
    expect(
      within(messageLog).getByText("Where is my order?"),
    ).toBeInTheDocument();
    expect(
      within(messageLog).getByText("Your order is on the way."),
    ).toBeInTheDocument();
    expect(
      within(messageLog).queryByText("Temporary preview response"),
    ).not.toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("marks a controlled fallback reply without exposing vendor errors", async () => {
    conversationService.listConversations.mockResolvedValue([conversation]);
    conversationService.listMessages.mockResolvedValue([
      {
        id: "message-user",
        role: "user",
        content: "Is my order delayed?",
        metadata: null,
        created_at: "2026-11-15T10:10:00Z",
      },
      {
        id: "message-assistant",
        role: "assistant",
        content: "I'm sorry, I can't generate a reply right now.",
        metadata: {
          source: "fallback",
          provider: "gemini",
          fallback: true,
          error: "rate_limit",
        },
        created_at: "2026-11-15T10:10:01Z",
      },
    ]);

    renderChat();

    expect(
      await screen.findByText(
        "Automated reply unavailable. Please try again.",
      ),
    ).toBeInTheDocument();
  });
});
