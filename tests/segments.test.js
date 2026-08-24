/* Тести для web/segments.js — того, що неможливо перевірити в браузері.
 *
 *   bun test tests/segments.test.js
 *
 * Голосовий шлях у браузерній панелі недоступний: доступ до мікрофона там
 * заблокований. А саме від цієї логіки залежить, чи дослідник побачить різницю
 * між сказаним вголос і набраним вручну — тому вона перевіряється тут.
 */

const { test, expect } = require("bun:test");
const S = require("../web/segments.js");

const voice = (text, clip = 0) => ({ text, source: "voice", clip });
const typed = (text) => ({ text, source: "typed", clip: null });

test("порожній шматок не додається", () => {
  expect(S.push([], "   ", "voice", 0)).toEqual([]);
  expect(S.push([], "", "typed")).toEqual([]);
});

test("сусідні шматки того самого запису зливаються", () => {
  let list = S.push([], "Їздили в Карпати", "voice", 0);
  list = S.push(list, "з друзями", "voice", 0);
  expect(list).toEqual([voice("Їздили в Карпати з друзями")]);
});

test("новий запис — новий шматок", () => {
  let list = S.push([], "Їздили в Карпати", "voice", 0);
  list = S.push(list, "нас було шість", "voice", 1);
  expect(list.length).toBe(2);
  expect(list[1].clip).toBe(1);
});

test("голос і текст не зливаються ніколи", () => {
  let list = S.push([], "Їздили в Карпати", "voice", 0);
  list = S.push(list, "з друзями з університету", "typed");
  expect(list.map((p) => p.source)).toEqual(["voice", "typed"]);
});

test("текст шматків склеюється в одну відповідь", () => {
  const list = [voice("Їздили в Карпати"), typed("нас було шість")];
  expect(S.text(list)).toBe("Їздили в Карпати нас було шість");
});

test("правка: недоторкане диктування лишається голосом", () => {
  const list = [voice("Їздили в Карпати")];
  const after = S.fromEdit(list, "Їздили в Карпати з друзями з університету");
  expect(after.map((p) => p.source)).toEqual(["voice", "typed"]);
  expect(after[0].text).toBe("Їздили в Карпати");
  expect(after[1].text).toBe("з друзями з університету");
  // Запис, до якого належав голос, не губиться — інакше підсвітка під час
  // прослуховування не знайшла б своїх слів.
  expect(after[0].clip).toBe(0);
});

test("правка: переписане з початку стає набраним", () => {
  const list = [voice("Їздили в Карпати")];
  const after = S.fromEdit(list, "Ми їздили в Карпати");
  expect(after).toEqual([typed("Ми їздили в Карпати")]);
});

test("правка: стерте лишає порожньо", () => {
  expect(S.fromEdit([voice("Їздили в Карпати")], "   ")).toEqual([]);
});

test("правка не губить сказане — це головна вимога", () => {
  const list = [voice("Їздили в Карпати, у Ворохту")];
  const value = S.text(list);
  expect(S.text(S.fromEdit(list, value))).toBe(value);
});

test("слова шматка рахуються для підсвітки", () => {
  expect(S.words(voice("Їздили в Карпати"))).toEqual(["Їздили", "в", "Карпати"]);
  expect(S.words({ text: "" })).toEqual([]);
  expect(S.words(null)).toEqual([]);
});
