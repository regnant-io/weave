"use client";

import type { LucideIcon, LucideProps } from "lucide-react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Atom,
  BarChart3,
  Boxes,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  Copy,
  Database,
  Download,
  ExternalLink,
  Eye,
  FileText,
  FlaskConical,
  Folder,
  Globe,
  Image as ImageIcon,
  Languages,
  Layers,
  Library,
  LogOut,
  Maximize2,
  MessageSquarePlus,
  Menu,
  Monitor,
  Moon,
  MoreVertical,
  Network,
  PanelLeft,
  PanelRightClose,
  Pencil,
  Play,
  Plus,
  Quote,
  RefreshCw,
  Search,
  Settings,
  Shapes,
  Sparkles,
  Square,
  Sun,
  Telescope,
  Terminal,
  Trash2,
  Upload,
  X,
} from "lucide-react";

/**
 * One place that decides icon weight and default size.
 *
 * design.md §Iconography: outlined, thin strokes (1.5), consistent sizing,
 * no filled shapes. Wrapping each icon here instead of importing lucide at
 * call sites keeps that rule enforceable — and it is what replaces the old
 * hand-typed glyphs (◇ ▤ ⚙ ✿ ◆ ▾ ↻ ⬇ ✦ « »), which never aligned to the
 * text baseline and rendered differently on every platform.
 */
const mk =
  (C: LucideIcon, defaultSize = 16) =>
  ({ size, strokeWidth, ...rest }: LucideProps) => (
    <C size={size ?? defaultSize} strokeWidth={strokeWidth ?? 1.5} {...rest} />
  );

/* navigation & chrome */
export const IcoMenu = mk(Menu, 18);
export const IcoClose = mk(X);
export const IcoPanelLeft = mk(PanelLeft, 17);
export const IcoPanelClose = mk(PanelRightClose, 17);
export const IcoMore = mk(MoreVertical, 17);
export const IcoChevronDown = mk(ChevronDown);
export const IcoChevronRight = mk(ChevronRight);
export const IcoArrowUp = mk(ArrowUp);
export const IcoArrowDown = mk(ArrowDown);
export const IcoPlus = mk(Plus);
export const IcoSettings = mk(Settings, 17);
export const IcoLogout = mk(LogOut, 17);
export const IcoSun = mk(Sun, 17);
export const IcoMoon = mk(Moon, 17);
export const IcoMonitor = mk(Monitor, 17);
export const IcoLanguages = mk(Languages, 17);

/* workspace */
export const IcoProjects = mk(Folder, 17);
export const IcoLibrary = mk(Library, 17);
export const IcoDataset = mk(Database, 17);
export const IcoUpload = mk(Upload);
export const IcoDownload = mk(Download);
export const IcoFile = mk(FileText);
export const IcoImage = mk(ImageIcon);
export const IcoQuote = mk(Quote);

/* agent activity */
export const IcoSearch = mk(Search);
export const IcoGlobe = mk(Globe);
export const IcoTelescope = mk(Telescope);
export const IcoTerminal = mk(Terminal);
export const IcoChart = mk(BarChart3);
export const IcoDeck = mk(Layers);
export const IcoCube = mk(Boxes);
export const IcoShapes = mk(Shapes);
export const IcoAtom = mk(Atom);
export const IcoFlask = mk(FlaskConical);
export const IcoNetwork = mk(Network);
export const IcoSparkles = mk(Sparkles);

/* state */
export const IcoCheck = mk(Check);
export const IcoDot = mk(Circle, 8);
export const IcoWarn = mk(AlertTriangle);
export const IcoStop = mk(Square);
export const IcoPlay = mk(Play);
export const IcoRetry = mk(RefreshCw);
export const IcoEdit = mk(Pencil);
export const IcoCopy = mk(Copy);
export const IcoTrash = mk(Trash2);
export const IcoEye = mk(Eye);
export const IcoExternal = mk(ExternalLink);
export const IcoMaximize = mk(Maximize2);
export const IcoNewChat = mk(MessageSquarePlus, 17);

/** Tool name -> icon, so a step chip is recognisable before it is read. */
export function iconForTool(tool?: string) {
  switch (tool) {
    case "web_search":
      return IcoGlobe;
    case "deep_research":
      return IcoTelescope;
    case "search_library":
      return IcoLibrary;
    case "run_analysis":
      return IcoTerminal;
    case "query_warehouse":
      return IcoDataset;
    case "generate_visual":
      return IcoChart;
    case "generate_deck":
      return IcoDeck;
    case "generate_3d":
      return IcoCube;
    case "create_diagram":
      return IcoShapes;
    case "create_simulation":
      return IcoAtom;
    case "create_animation":
      return IcoSparkles;
    case "check_citation":
      return IcoQuote;
    default:
      return IcoSparkles;
  }
}
