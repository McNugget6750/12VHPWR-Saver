// *************************************************************************************************** //
// ********************************* Thermocouple Variables ****************************************** //
// *************************************************************************************************** //
// Check https://learn.adafruit.com/thermistor/using-a-thermistor for more info
// resistance at 25 degrees C
#define THERMISTORNOMINAL 100000 // 100k thermistor
// temp. for nominal resistance (almost always 25 C)
#define TEMPERATURENOMINAL 25
// The beta coefficient of the thermistor (usually 3000-4000)
#define BCOEFFICIENT 3950
// the value of the 'other' resistor
#define SERIESRESISTOR 4700 // 4.7k resistor

#define TEMPERATURE_PIN_0 A0
#define TEMPERATURE_PIN_1 A1
#define TEMPERATURE_PIN_2 A2
#define TEMPERATURE_PIN_3 A3

volatile uint16_t temperature_0 = 0;

void setup() {
  Serial.begin(115200);
  // put your setup code here, to run once:
  pinMode(TEMPERATURE_PIN_0, INPUT);
  pinMode(TEMPERATURE_PIN_1, INPUT);
  pinMode(TEMPERATURE_PIN_2, INPUT);
  pinMode(TEMPERATURE_PIN_3, INPUT);
}

int readTemperature(uint8_t pinnumber)
{
  float adc_temp_value = 0;
  float steinhart = 0;

  adc_temp_value = analogRead(pinnumber);

  // convert the value to resistance
  adc_temp_value = 1023.0f / adc_temp_value - 1;
  adc_temp_value = SERIESRESISTOR / adc_temp_value;
  
  steinhart = adc_temp_value / THERMISTORNOMINAL;       // (R/Ro)
  steinhart = log(steinhart);                           // ln(R/Ro)
  steinhart /= BCOEFFICIENT;                            // 1/B * ln(R/Ro)
  steinhart += 1.0f / (TEMPERATURENOMINAL + 273.15);     // + (1/To)
  steinhart = 1.0f / steinhart;                          // Invert
  steinhart -= 273.15f;                                  // convert to C
  
  return (int)(steinhart);
}

void loop() {
  // put your main code here, to run repeatedly:
  Serial.print("Temp 0: ");
  Serial.print(readTemperature(TEMPERATURE_PIN_0) > 0 ? readTemperature(TEMPERATURE_PIN_0) : 0);
  Serial.println("C");
  Serial.print("Temp 1: ");
  Serial.print(readTemperature(TEMPERATURE_PIN_1) > 0 ? readTemperature(TEMPERATURE_PIN_1) : 0);
  Serial.println("C");
  Serial.print("Temp 2: ");
  Serial.print(readTemperature(TEMPERATURE_PIN_2) > 0 ? readTemperature(TEMPERATURE_PIN_2) : 0);
  Serial.println("C");
  Serial.print("Temp 3: ");
  Serial.print(readTemperature(TEMPERATURE_PIN_3) > 0 ? readTemperature(TEMPERATURE_PIN_3) : 0);
  Serial.println("C");

  _delay_ms(1000);
}
