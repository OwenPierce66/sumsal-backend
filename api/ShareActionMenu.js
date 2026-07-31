import React from 'react';
import { Modal, View, Text, TouchableOpacity, StyleSheet, SafeAreaView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

const ShareActionMenu = ({ isVisible, onClose, onShare, onRepost, onShareToStory }) => {
  if (!isVisible) {
    return null;
  }

  return (
    <Modal
      transparent={true}
      animationType="slide"
      visible={isVisible}
      onRequestClose={onClose}
    >
      <TouchableOpacity style={styles.overlay} activeOpacity={1} onPressOut={onClose}>
        <View style={styles.container}>
          <Text style={styles.title}>Compartir</Text>
          
          <TouchableOpacity style={styles.option} onPress={onShare}>
            <Ionicons name="chatbubble-ellipses-outline" size={24} color="#333" />
            <Text style={styles.optionText}>Compartir con descripción</Text>
          </TouchableOpacity>

          <TouchableOpacity style={styles.option} onPress={onRepost}>
            <Ionicons name="repeat-outline" size={24} color="#333" />
            <Text style={styles.optionText}>Repostear ahora</Text>
          </TouchableOpacity>

          <TouchableOpacity style={styles.option} onPress={onShareToStory}>
            <Ionicons name="add-circle-outline" size={24} color="#333" />
            <Text style={styles.optionText}>Compartir en tu historia</Text>
          </TouchableOpacity>

          <TouchableOpacity style={styles.cancelOption} onPress={onClose}>
            <Text style={styles.cancelText}>Cancelar</Text>
          </TouchableOpacity>
        </View>
      </TouchableOpacity>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'flex-end',
  },
  container: {
    backgroundColor: 'white',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    padding: 16,
    paddingBottom: 30, // Safe area for bottom gestures
  },
  title: {
    fontSize: 18,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 15,
    color: '#333',
  },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 15,
    borderBottomWidth: 1,
    borderBottomColor: '#f0f0f0',
  },
  optionText: {
    marginLeft: 15,
    fontSize: 16,
    color: '#333',
  },
  cancelOption: {
    marginTop: 10,
    paddingVertical: 15,
    alignItems: 'center',
  },
  cancelText: {
    fontSize: 16,
    color: 'red',
    fontWeight: '600',
  },
});

export default ShareActionMenu;