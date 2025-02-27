from arena_server.controller import Controller
from arena_server.wifi_parameter import WiFiParam
from typing import TYPE_CHECKING, Dict, List
import itertools
import tensorflow as tf
import numpy as np
if TYPE_CHECKING:
    from arena_server.wifi_network_operator import WiFiNetworkOperator


class TrainedController(Controller):
    def __init__(self, model, max_num_unit_packet: int, observation_history_length: int,
                 sensing_unit_packet_length_ratio: int, unit_packet_success_reward: float,
                 unit_packet_failure_reward: float):
        super().__init__()
        self._model = model
        self._freq_channel_list: List[int] = []
        self._num_freq_channel = 0
        self._max_num_unit_packet = max_num_unit_packet
        self._freq_channel_combination = []
        self._num_freq_channel_combination = 0
        self._num_action = 0
        self._observation_history_length = observation_history_length
        self._sensing_unit_packet_length_ratio = sensing_unit_packet_length_ratio
        self._observation_history = np.empty(0)
        self._cca_thresh = -70
        self._action_dict = {'type': 'sensing'}
        self._latest_observation_dict = None
        self._unit_packet_success_reward = unit_packet_success_reward
        self._unit_packet_failure_reward = unit_packet_failure_reward

    def set_network_operator(self, network_operator: 'WiFiNetworkOperator'):
        super().set_network_operator(network_operator)
        self._num_freq_channel = len(network_operator.freq_channel_list)
        self._freq_channel_combination = [np.where(np.flip(np.array(x)))[0].tolist()
                                          for x in itertools.product((0, 1), repeat=self._num_freq_channel)][1:]
        self._num_freq_channel_combination = 2 ** self._num_freq_channel - 1
        self._num_action = self._num_freq_channel_combination * self._max_num_unit_packet + 1
        self._observation_history = np.zeros((self._observation_history_length, self._num_freq_channel, 2))

    def request_decision(self, observation: Dict) -> Dict:
        self.update_observation_history(self._action_dict, observation)
        action_index = self.get_next_action(observation=self._observation_history)
        self._action_dict = self.convert_action_index_to_dict(action_index=action_index)
        return self._action_dict

    def get_next_action(self, observation: np.ndarray):
        action, _, _ = self.get_dnn_action_and_value(self._model, observation)
        return int(action)

    def convert_action_index_to_dict(self, action_index: int) -> Dict:
        """ Convert action index to dictionary form
        Args:
            action_index: index of action (0: sensing, 1 to (2^num_freq_channel-1)*max_num_unit_packet: tx_data_packet)
        Returns:
            action in dictionary form
                'type': 'sensing' or 'tx_data_packet',
                'freq_channel_list': list of frequency channels for data transmission
                'num_unit_packet': number of unit packets
        """
        if action_index == 0:
            action_dict = {'type': 'sensing'}
        else:
            num_unit_packet = (action_index - 1) // self._num_freq_channel_combination + 1
            freq_channel_combination_index = (action_index - 1) % self._num_freq_channel_combination
            freq_channel_list = self._freq_channel_combination[freq_channel_combination_index]
            action_dict = {'type': 'tx_data_packet', 'freq_channel_list': freq_channel_list,
                           'num_unit_packet': num_unit_packet}
        return action_dict

    @staticmethod
    def get_dnn_action_and_value(dnn: tf.keras.Model, observation: np.ndarray):
        single = False
        if observation.ndim == 3:
            observation = observation[np.newaxis, ...]
            single = True
        action_value = dnn.predict(observation)
        best_action = np.argmax(action_value, axis=1)
        best_value = np.amax(action_value, axis=1)
        if single:
            best_action = best_action[0]
            best_value = best_value[0]
            action_value = action_value[0]
        return best_action, best_value, action_value

    def update_observation_history(self, action: Dict, observation: Dict):
        observation_type = observation['type']
        new_observation = np.zeros((self._num_freq_channel, 2))
        new_observation_length = 1
        if observation_type == 'sensing':
            sensed_power = observation['sensed_power']
            occupied_channel_list = [int(freq_channel) for freq_channel in sensed_power
                                     if sensed_power[freq_channel] > self._cca_thresh]
            new_observation[occupied_channel_list, 0] = 1
            new_observation_length = 1
        elif observation_type == 'tx_data_packet':
            tx_freq_channel_list = action['freq_channel_list']
            success_freq_channel_list = observation['success_freq_channel_list']
            failure_freq_channel_list = list(set(tx_freq_channel_list) - set(success_freq_channel_list))
            num_unit_packet = action['num_unit_packet']
            new_observation[failure_freq_channel_list, 1] = 1
            new_observation_length = num_unit_packet * self._sensing_unit_packet_length_ratio
        new_observation = np.broadcast_to(new_observation, (new_observation_length, self._num_freq_channel, 2))
        self._observation_history = np.concatenate((new_observation, self._observation_history),
                                                   axis=0)[:self._observation_history_length, ...]


class TrainedControllerC51(Controller):
    def __init__(self, model, max_num_unit_packet: int, observation_history_length: int,
                 sensing_unit_packet_length_ratio: int, unit_packet_success_reward: float,
                 unit_packet_failure_reward: float, num_support: int, v_max: int, v_min: int):
        super().__init__()
        self._model = model
        self._freq_channel_list: List[int] = []
        self._num_freq_channel = 0
        self._max_num_unit_packet = max_num_unit_packet
        self._freq_channel_combination = []
        self._num_freq_channel_combination = 0
        self._num_action = 0
        self._observation_history_length = observation_history_length
        self._sensing_unit_packet_length_ratio = sensing_unit_packet_length_ratio
        self._observation_history = np.empty(0)
        self._cca_thresh = -70
        self._action_dict = {'type': 'sensing'}
        self._latest_observation_dict = None
        self._unit_packet_success_reward = unit_packet_success_reward
        self._unit_packet_failure_reward = unit_packet_failure_reward

        self._num_support = num_support
        self._V_max = v_max
        self._V_min = v_min
        self._dz = float(self._V_max - self._V_min) / (self._num_support - 1)
        self._z = np.linspace(self._V_min, self._V_max, self._num_support)      # supports

    def set_network_operator(self, network_operator: 'WiFiNetworkOperator'):
        super().set_network_operator(network_operator)
        self._num_freq_channel = len(network_operator.freq_channel_list)
        self._freq_channel_combination = [np.where(np.flip(np.array(x)))[0].tolist()
                                          for x in itertools.product((0, 1), repeat=self._num_freq_channel)][1:]
        self._num_freq_channel_combination = 2 ** self._num_freq_channel - 1
        self._num_action = self._num_freq_channel_combination * self._max_num_unit_packet + 1
        self._observation_history = np.zeros((self._observation_history_length, self._num_freq_channel, 2))

    def request_decision(self, observation: Dict) -> Dict:
        self.update_observation_history(self._action_dict, observation)
        action_index = self.get_next_action(observation=self._observation_history)
        self._action_dict = self.convert_action_index_to_dict(action_index=action_index)
        return self._action_dict

    def get_next_action(self, observation: np.ndarray):
        action, _, _ = self.get_dnn_action_and_value(self._model, observation, self._z, self._num_action)
        return int(action)

    def convert_action_index_to_dict(self, action_index: int) -> Dict:
        """ Convert action index to dictionary form
        Args:
            action_index: index of action (0: sensing, 1 to (2^num_freq_channel-1)*max_num_unit_packet: tx_data_packet)
        Returns:
            action in dictionary form
                'type': 'sensing' or 'tx_data_packet',
                'freq_channel_list': list of frequency channels for data transmission
                'num_unit_packet': number of unit packets
        """
        if action_index == 0:
            action_dict = {'type': 'sensing'}
        else:
            num_unit_packet = (action_index - 1) // self._num_freq_channel_combination + 1
            freq_channel_combination_index = (action_index - 1) % self._num_freq_channel_combination
            freq_channel_list = self._freq_channel_combination[freq_channel_combination_index]
            action_dict = {'type': 'tx_data_packet', 'freq_channel_list': freq_channel_list,
                           'num_unit_packet': num_unit_packet}
        return action_dict

    @staticmethod
    def get_dnn_action_and_value(dnn: tf.keras.Model, observation: np.ndarray, z: np.ndarray, num_action: int):
        single = False
        if observation.ndim == 3:
            observation = observation[np.newaxis, ...]
            single = True

        action_distribution_value = dnn.predict(observation)
        # print(np.shape(action_distribution_value))
        if single:
            # distribution -> scalar
            z_space = np.repeat(np.expand_dims(z, axis=0), num_action, axis=0)
            action_value = np.sum(action_distribution_value[0] * z_space, axis=1)  # 46개중에 몇번째?
            best_action = np.argmax(action_value, axis=0)                          # 그 q_value 값은?
            best_value = np.amax(action_value, axis=0)                             # 전체 46action 에 대한 각각의 Q값
            return best_action, best_value, action_value

        elif not single:
            return  action_distribution_value

    def update_observation_history(self, action: Dict, observation: Dict):
        observation_type = observation['type']
        new_observation = np.zeros((self._num_freq_channel, 2))
        new_observation_length = 1
        if observation_type == 'sensing':
            sensed_power = observation['sensed_power']
            occupied_channel_list = [int(freq_channel) for freq_channel in sensed_power
                                     if sensed_power[freq_channel] > self._cca_thresh]
            new_observation[occupied_channel_list, 0] = 1
            new_observation_length = 1
        elif observation_type == 'tx_data_packet':
            tx_freq_channel_list = action['freq_channel_list']
            success_freq_channel_list = observation['success_freq_channel_list']
            failure_freq_channel_list = list(set(tx_freq_channel_list) - set(success_freq_channel_list))
            num_unit_packet = action['num_unit_packet']
            new_observation[failure_freq_channel_list, 1] = 1
            new_observation_length = num_unit_packet * self._sensing_unit_packet_length_ratio
        new_observation = np.broadcast_to(new_observation, (new_observation_length, self._num_freq_channel, 2))
        self._observation_history = np.concatenate((new_observation, self._observation_history),
                                                   axis=0)[:self._observation_history_length, ...]