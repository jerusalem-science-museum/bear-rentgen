/*
 * Reader firmware: Pro Micro (ATmega32U4) + MFRC522 RFID module + buzzer.
 * Wiring: schematics.pdf. Protocol and behaviour: README.md.
 *
 * Sends text lines over USB serial:
 *   S <card id>   a Scan (decimal number from the first 4 UID bytes)
 *   L <text>      a Reader Report (boot, Module Reinit results)
 *
 * Needs the "MFRC522" library by GithubCommunity (miguelbalboa), version 1.4+.
 */

#include <SPI.h>
#include <MFRC522.h>
#include <avr/wdt.h>

const uint8_t BUZZER_PIN = 7;  // active high
const uint8_t SS_PIN = 10;
const unsigned long HEALTH_CHECK_MS = 5000UL;
const unsigned long PERIODIC_REINIT_MS = 10UL * 60UL * 1000UL;
const uint8_t REINIT_ATTEMPTS = 3;
const unsigned int BEEP_MS = 200;

// The module's RST pin is wired to the Pro Micro's RST, not to a GPIO, so
// the library can't hard-reset it; PCD_Init() falls back to a soft reset.
MFRC522 rfid(SS_PIN, MFRC522::UNUSED_PIN);

unsigned long lastHealthCheck = 0;
unsigned long lastReinit = 0;
char bootReport[48];
bool bootReportPending = true;

// Pet the watchdog, except after the 1200-baud "touch" that arduino-cli sends
// to start an upload: the core then arms a 120 ms watchdog reset into the
// bootloader, and petting it here would cancel that reset and break uploads.
void feedWatchdog() {
  if (Serial.baud() != 1200) wdt_reset();
}

// Health Check: the module answers VersionReg with its chip version.
// 0x00 / 0xFF means nothing is answering on SPI.
bool moduleAlive(byte &version) {
  version = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  return version != 0x00 && version != 0xFF;
}

// Module Reinit, retried a few times. Returns the final version byte.
bool reinitModule(byte &version, uint8_t &attempts) {
  for (attempts = 1; attempts <= REINIT_ATTEMPTS; attempts++) {
    feedWatchdog();
    rfid.PCD_Init();
    delay(4);  // some modules need a moment after init
    if (moduleAlive(version)) return true;
  }
  attempts = REINIT_ATTEMPTS;
  return false;
}

void reportReinit(const char *reason, byte badVersion) {
  byte version;
  uint8_t attempts;
  bool ok = reinitModule(version, attempts);
  char line[96];
  snprintf(line, sizeof line,
           "L reinit reason=%s before=0x%02X result=%s attempts=%u version=0x%02X",
           reason, badVersion, ok ? "ok" : "failed", attempts, version);
  Serial.println(line);  // dropped silently if the Pi isn't listening
  lastReinit = lastHealthCheck = millis();
}

void sendScan(const byte *uid) {
  uint32_t id = ((uint32_t)uid[0] << 24) | ((uint32_t)uid[1] << 16) |
                ((uint32_t)uid[2] << 8) | (uint32_t)uid[3];
  Serial.print("S ");
  Serial.println(id);
}

void beep() {
  digitalWrite(BUZZER_PIN, HIGH);
  delay(BEEP_MS);
  digitalWrite(BUZZER_PIN, LOW);
}

void setup() {
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  Serial.begin(9600);  // baud is ignored on native USB; never wait for the port
  SPI.begin();
  wdt_enable(WDTO_4S);  // reboot the board if loop() ever stalls for 4 s

  byte version;
  uint8_t attempts;
  bool ok = reinitModule(version, attempts);
  snprintf(bootReport, sizeof bootReport, "L boot module=%s version=0x%02X",
           ok ? "ok" : "failed", version);
  lastReinit = lastHealthCheck = millis();
}

void loop() {
  feedWatchdog();
  unsigned long now = millis();

  // The Pi usually opens the port a few seconds after boot; hold the boot
  // report until it does (Serial is true once the host has the port open).
  if (bootReportPending && Serial) {
    Serial.println(bootReport);
    bootReportPending = false;
  }

  if (now - lastReinit >= PERIODIC_REINIT_MS) {
    reportReinit("periodic", rfid.PCD_ReadRegister(MFRC522::VersionReg));
  } else if (now - lastHealthCheck >= HEALTH_CHECK_MS) {
    lastHealthCheck = now;
    byte version;
    if (!moduleAlive(version)) reportReinit("check_failed", version);
  }

  if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
    sendScan(rfid.uid.uidByte);
    beep();
    rfid.PICC_HaltA();  // put this tag to sleep so it isn't scanned again until it's lifted off
    rfid.PCD_StopCrypto1();  // Stop encryption on PCD
  }
}
