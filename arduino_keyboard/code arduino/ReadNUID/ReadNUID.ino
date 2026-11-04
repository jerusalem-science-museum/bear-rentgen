/*
 * Keyboard emulator that "print" RFIF NUID  
 * Next FROM 
 * https://github.com/miguelbalboa/rfid
 * --------------------------------------------------------------------------------------------------------------------
 * Example sketch/program showing how to read new NUID from a PICC to serial.
 * --------------------------------------------------------------------------------------------------------------------
 * This is a MFRC522 library example; for further details and other examples see: https://github.com/miguelbalboa/rfid
 * 
 * Example sketch/program showing how to the read data from a PICC (that is: a RFID Tag or Card) using a MFRC522 based RFID
 * Reader on the Arduino SPI interface.
 * 
 * When the Arduino and the MFRC522 module are connected (see the pin layout below), load this sketch into Arduino IDE
 * then verify/compile and upload it. To see the output: use Tools, Serial Monitor of the IDE (hit Ctrl+Shft+M). When
 * you present a PICC (that is: a RFID Tag or Card) at reading distance of the MFRC522 Reader/PCD, the serial output
 * will show the type, and the NUID if a new card has been detected. Note: you may see "Timeout in communication" messages
 * when removing the PICC from reading distance too early.
 * 
 * @license Released into the public domain.
 * 
 * Typical pin layout used:
 * -----------------------------------------------------------------------------------------
 *             MFRC522      Arduino       Arduino   Arduino    Arduino          Arduino
 *             Reader/PCD   Uno/101       Mega      Nano v3    Leonardo/Micro   Pro Micro
 * Signal      Pin          Pin           Pin       Pin        Pin              Pin
 * -----------------------------------------------------------------------------------------
 * RST/Reset   RST          9             5         D9         RESET/ICSP-5     RST
 * SPI SS      SDA(SS)      10            53        D10        10               10
 * SPIbb
 * SPI MISO    MISO         12 / ICSP-1   50        D12        ICSP-1           14
 * SPI SCK     SCK          13 / ICSP-3   52        D13        ICSP-3           15
 *
 * More pin layouts for other boards can be found here: https://github.com/miguelbalboa/rfid#pin-layout
 */

#include <Keyboard.h>
#include <SPI.h>
#include <MFRC522.h>
#define BUZ_PIN 7 //buzzer output active high 
#define SS_PIN 10
#define RST_PIN 9 ///not used. the RST_PIN RFID is connected to the RST PIN of the arduino
 
MFRC522 rfid(SS_PIN, RST_PIN); // Instance of the class

void setup() { 
  pinMode(BUZ_PIN, OUTPUT);//
  digitalWrite(BUZ_PIN, LOW);//no sound
  Keyboard.begin();
  //Serial.begin(9600);
  SPI.begin(); // Init SPI bus
  rfid.PCD_Init(); // Init MFRC522 
  //Keyboard.println("MIFARE Classsic NUID tester");
}
 
void loop() {

  // Reset the loop if no new card present on the sensor/reader. This saves the entire process when idle.
  if( ! rfid.PICC_IsNewCardPresent()){
    //Serial.println("NO TAG");
    return;
    }

  // Verify if the NUID has been readed
  if( ! rfid.PICC_ReadCardSerial()){
    //Serial.println("NO NUID READ");
    return;
    }

  //Serial.print(F("the PICC type is: "));
  MFRC522::PICC_Type piccType = rfid.PICC_GetType(rfid.uid.sak);

  //Serial.println(F("A new card has been detected."));
  digitalWrite(BUZ_PIN, HIGH);
  delay(200);//0.5 sec beep
  digitalWrite(BUZ_PIN, LOW);
  KeySend(rfid.uid.uidByte, rfid.uid.size);
  // Halt PICC
  rfid.PICC_HaltA();
  // Stop encryption on PCD
  rfid.PCD_StopCrypto1();
}


void KeySend(byte *buffer, byte bufferSize) {
    uint32_t rfid_NUID = 0;
    rfid_NUID += buffer[0] << 24;
    rfid_NUID += buffer[1] << 16; 
    rfid_NUID += buffer[2] << 8;
    rfid_NUID += buffer[3]; 
    String thisString = String(rfid_NUID);
    Keyboard.println(thisString);      
    //Serial.println(thisString);      
    //Keyboard.println("===============");
}

