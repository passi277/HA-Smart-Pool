"""Pool task list (season checklists, maintenance) for Smart Pool."""

from __future__ import annotations

import uuid

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SmartPoolConfigEntry
from .entity import SmartPoolEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the task list."""
    async_add_entities([SmartPoolTodo(entry.runtime_data, "tasks")])


class SmartPoolTodo(SmartPoolEntity, TodoListEntity):
    """Tasks Smart Pool adds automatically; editable like any list."""

    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the items."""
        return [
            TodoItem(
                uid=item["uid"],
                summary=item["summary"],
                status=TodoItemStatus(item["status"]),
                description=item.get("description"),
            )
            for item in self.controller.todo_items
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item."""
        self.controller.todo_items.append(
            {
                "uid": uuid.uuid4().hex,
                "summary": item.summary or "",
                "status": str(item.status or TodoItemStatus.NEEDS_ACTION),
                "description": item.description,
            }
        )
        await self.controller.async_todo_changed()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update an item."""
        for stored in self.controller.todo_items:
            if stored["uid"] == item.uid:
                if item.summary is not None:
                    stored["summary"] = item.summary
                if item.status is not None:
                    stored["status"] = str(item.status)
                stored["description"] = item.description
        await self.controller.async_todo_changed()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items."""
        self.controller.todo_items[:] = [
            i for i in self.controller.todo_items if i["uid"] not in uids
        ]
        await self.controller.async_todo_changed()
