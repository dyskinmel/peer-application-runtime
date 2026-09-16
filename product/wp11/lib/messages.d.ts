import type { Message } from './types.js';
export declare function message(key: string, args?: Readonly<Record<string, string | number>>): Message;
export declare function formatMessage(input: Message, locale: 'ja' | 'en'): string;
