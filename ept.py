import re
import yaml
import json
import os
import logging
from confluent_kafka import Consumer, KafkaError, Producer


class LogParser:
    def __init__(self, config_path):
        self.setup_logging()
        self.config = self.load_config(config_path)

        self.successful_logs = 0  
        self.failed_logs = 0      


    def setup_logging(self):
        current_file = os.path.basename(__file__)
        logging.basicConfig(
            filename="log_parser.log",
            filemode="a",
            format=f"%(asctime)s - %(levelname)s - {current_file} - %(message)s",
            level=logging.DEBUG
        )
        logging.info("Initialized LogParser")

    def load_config(self, config_path):
        try:
            with open(config_path, 'r') as file:
                logging.info(f"Loading configuration from {config_path}")
                return yaml.safe_load(file)
        except Exception as e:
            logging.error(f"Failed to load configuration: {e}")
            raise

    def strip_ansi_codes(self, text):
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def parse_log_entry(self, log):
        log = self.strip_ansi_codes(log)
        regex = re.compile(self.config['log_pattern']['regex'], re.VERBOSE)
        match = regex.match(log)
        if match:
            return match.groupdict()
        return None

    def process_log(self, full_log, producer):
        log_text = " ".join(full_log)
        parsed_entry = self.parse_log_entry(log_text)
        log_file_path = self.config['file_paths']['log_file']
        base_filename = os.path.splitext(os.path.basename(log_file_path))[0]

        if parsed_entry:
            parsed_entry['log_file'] = base_filename
            producer.produce('logs', value=json.dumps(parsed_entry))
            producer.flush()
            self.successful_logs += 1
        else:
            logging.warning(f"Failed to parse log entry: {log_text}")
            self.failed_logs += 1

    def parse_log_file(self):
        consumer_config = {
            'bootstrap.servers': self.config['kafka']['bootstrap_servers'],
            'group.id': self.config['kafka']['group_id'],
            'auto.offset.reset': 'earliest'
        }

        producer_config = {
            'bootstrap.servers': self.config['kafka']['bootstrap_servers'],
            'client.id': 'python-producer'
        }

        consumer = Consumer(consumer_config)
        producer = Producer(producer_config)
        consumer.subscribe([self.config['kafka']['topic']])

        try:
            full_log = []

            while True:
                msg = consumer.poll(timeout=1.0)

                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        logging.error(f"Kafka error: {msg.error()}")
                        break

                log_message = msg.value().decode('utf-8')
                lines = log_message.splitlines()

                for line in lines:
                    line = self.strip_ansi_codes(line)
                    if line.startswith("[v "):
                        if full_log:
                            self.process_log(full_log, producer)
                        full_log = [line.strip()]
                    else:
                        full_log.append(line)

                if full_log:
                    self.process_log(full_log, producer)

        except KeyboardInterrupt:
            logging.info("Process interrupted by user.")
        finally:
            consumer.close()


        logging.info(f"Log parsing completed.")
        logging.info(f"Successful logs: {self.successful_logs}")
        logging.info(f"Failed logs: {self.failed_logs}")    

if __name__ == "__main__":
    parser = LogParser("config.yaml")
    parser.parse_log_file()
