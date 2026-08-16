"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ScheduledTasks } from "./components/ScheduledTasks";
import { useScheduledTasksContainer } from "./containers/useScheduledTasksContainer";

export const ScheduledTasksPage = createReactContainer(
  "ScheduledTasksPage",
  useScheduledTasksContainer,
  ScheduledTasks,
);
