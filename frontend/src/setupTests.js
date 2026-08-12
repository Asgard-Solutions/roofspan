// Jest DOM matchers for React Testing Library (auto-loaded by CRA/craco test).
import "@testing-library/jest-dom";
import { TextEncoder, TextDecoder } from "util";

// react-router v7 references TextEncoder/TextDecoder, which this jsdom build doesn't expose.
if (typeof global.TextEncoder === "undefined") global.TextEncoder = TextEncoder;
if (typeof global.TextDecoder === "undefined") global.TextDecoder = TextDecoder;

// React 19 act() environment flag (so RTL async updates are wrapped without warnings).
global.IS_REACT_ACT_ENVIRONMENT = true;
