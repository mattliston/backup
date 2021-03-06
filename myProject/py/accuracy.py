#!/usr/bin/env python
# coding: utf-8

# # Imports

#get_ipython().system('pip3 install --upgrade tensorflow-model-optimization')
#get_ipython().system('pip3 install mat4py')

import numpy as np
import tensorflow as tf
import tensorflow_model_optimization as tfmot
import matplotlib.pyplot as plt
import json
import tempfile

from mat4py import loadmat

print(tf.__version__)
print(np.__version__)


# # Data pre-processing


def downscale(data, resolution):

    # 10 min resolution.. (data.shape[0], 3, 1440) -> (data.shape[0], 10, 3, 144).. breaks one 3,1440 length trajectory into ten 3,144 length trajectories
    # Use ~12 timesteps -> 2-5 timesteps (Use ~2 hours to predict 20-50 mins)

    return np.mean(data.reshape(data.shape[0], data.shape[1], int(data.shape[2]/resolution), resolution), axis=3)

def process_data(aligned_data, time_horizon, ph):

    # 10 min resolution.. breaks each (3,144) trajectory into (144-ph-time_horizon,3,time_horizon) samples

    data = np.zeros((aligned_data.shape[0] * (aligned_data.shape[2]-ph-time_horizon), aligned_data.shape[1], time_horizon))
    label = np.zeros((aligned_data.shape[0] * (aligned_data.shape[2]-ph-time_horizon), ph))

    count = 0
    for i in range(aligned_data.shape[0]): # for each sample
        for j in range(aligned_data.shape[2]-ph-time_horizon): # TH length sliding window across trajectory
                data[count] = aligned_data[i,:,j:j+time_horizon]
                label[count] = aligned_data[i,0,j+time_horizon:j+time_horizon+ph]
                count+=1     

    return data, label

def load_mpc(time_horizon, ph, resolution, batch): # int, int, int, bool
    
    # Load train data
    g = np.loadtxt('CGM_prediction_data/glucose_readings_train.csv', delimiter=',')
    c = np.loadtxt('CGM_prediction_data/meals_carbs_train.csv', delimiter=',') 
    it = np.loadtxt('CGM_prediction_data/insulin_therapy_train.csv', delimiter=',')

    # Load test data
    g_ = np.loadtxt('CGM_prediction_data/glucose_readings_test.csv', delimiter=',')
    c_ = np.loadtxt('CGM_prediction_data/meals_carbs_test.csv', delimiter=',')
    it_ = np.loadtxt('CGM_prediction_data/insulin_therapy_test.csv', delimiter=',')

    # Time align train & test data
    aligned_train_data = downscale(np.array([(g[i,:], c[i,:], it[i,:]) for i in range(g.shape[0])]), resolution)
    aligned_test_data = downscale(np.array([(g_[i,:], c_[i,:], it_[i,:]) for i in range(g_.shape[0])]), resolution)
    print(aligned_train_data.shape)

    # Break time aligned data into train & test samples
    if batch:
        train_data, train_label = process_data(aligned_train_data, time_horizon, ph)
        test_data, test_label = process_data(aligned_test_data, time_horizon, ph)
    
        return np.swapaxes(train_data,1,2), train_label, np.swapaxes(test_data,1,2), test_label
      
    else:

        return aligned_train_data, aligned_test_data

def load_uva(time_horizon, ph, resolution, batch):

    data = loadmat('uva-padova-data/sim_results.mat')
    train_data = np.zeros((231,3,1440))
    test_data = np.zeros((99,3,1440))

    # Separate train and test sets.. last 3 records of each patient will be used for testing
    count_train = 0
    count_test = 0
    for i in range(33):
        for j in range(10):

            if j>=7:
                test_data[count_test,0,:] = np.asarray(data['data']['results']['sensor'][count_test+count_train]['signals']['values']).flatten()[:1440]
                test_data[count_test,1,:] = np.asarray(data['data']['results']['CHO'][count_test+count_train]['signals']['values']).flatten()[:1440]
                test_data[count_test,2,:] = np.asarray(data['data']['results']['BOLUS'][count_test+count_train]['signals']['values']).flatten()[:1440] + np.asarray(data['data']['results']['BASAL'][i]['signals']['values']).flatten()[:1440]
                count_test+=1
            else:

                train_data[count_train,0,:] = np.asarray(data['data']['results']['sensor'][count_test+count_train]['signals']['values']).flatten()[:1440]
                train_data[count_train,1,:] = np.asarray(data['data']['results']['CHO'][count_test+count_train]['signals']['values']).flatten()[:1440]
                train_data[count_train,2,:] = np.asarray(data['data']['results']['BOLUS'][count_test+count_train]['signals']['values']).flatten()[:1440] + np.asarray(data['data']['results']['BASAL'][i]['signals']['values']).flatten()[:1440]
                count_train+=1

    train_data = downscale(train_data, resolution)
    test_data = downscale(test_data, resolution)

    if batch: 
        train_data, train_label = process_data(train_data, time_horizon, ph)
        test_data, test_label = process_data(test_data, time_horizon, ph)
    
        return np.swapaxes(train_data,1,2)*0.0555, train_label*0.0555, np.swapaxes(test_data,1,2)*0.0555, test_label*0.0555 # convert to mmol/L

    else:
        
        return train_data, test_data


# # Define models

# ## LSTM


def lstm(ph, training):

    inp = tf.keras.Input(shape=(train_data.shape[1], train_data.shape[2]))
    model = tf.keras.layers.LSTM(200, return_sequences=True)(inp)
    model = tf.keras.layers.Dropout(rate=0.5)(model, training=training)
    model = tf.keras.layers.LSTM(200, return_sequences=True)(model)
    model = tf.keras.layers.Dropout(rate=0.5)(model, training=training)
    model = tf.keras.layers.LSTM(200, return_sequences=True)(model)
    model = tf.keras.layers.Dropout(rate=0.5)(model, training=training)
    model = tf.keras.layers.Flatten()(model)
    model = tf.keras.layers.Dense(ph, activation=None)(model)

    x = tf.keras.Model(inputs=inp, outputs=model)

    x.compile(optimizer='adam', loss='mean_squared_error', metrics=[tf.keras.metrics.RootMeanSquaredError(), loss_metric1, loss_metric2, loss_metric3, loss_metric4, loss_metric5, loss_metric6])
    
    return x


# ## CRNN


def crnn(ph, training):
  
    inp = tf.keras.Input(shape=(train_data.shape[1], train_data.shape[2]))
    model = tf.keras.layers.Conv1D(256, 4, activation='relu', padding='same')(inp)
    model = tf.keras.layers.MaxPool1D(pool_size=2, strides=1, padding='same')(model)
    model = tf.keras.layers.Dropout(rate=0.5)(model, training=training)
    model = tf.keras.layers.Conv1D(512, 4, activation='relu', padding='same')(model)
    model = tf.keras.layers.MaxPool1D(pool_size=2, strides=1, padding='same')(model)
    model = tf.keras.layers.Dropout(rate=0.5)(model, training=training)
    model = tf.keras.layers.LSTM(200, return_sequences=True)(model)
    model = tf.keras.layers.Dropout(rate=0.5)(model, training=training)
    model = tf.keras.layers.Flatten()(model)
    model = tf.keras.layers.Dense(ph, activation=None)(model)

    x = tf.keras.Model(inputs=inp, outputs=model)

    x.compile(optimizer='adam', loss='mean_squared_error', metrics=[tf.keras.metrics.RootMeanSquaredError(), loss_metric1, loss_metric2, loss_metric3, loss_metric4, loss_metric5, loss_metric6])
    
    return x


# ## Bidirectional LSTM


def bilstm(ph, training):

    inp = tf.keras.Input(shape=(train_data.shape[1], train_data.shape[2]))
    model = tf.keras.layers.Bidirectional(tf.keras.layers.LSTM(200, return_sequences=True))(inp)
    model = tf.keras.layers.Dropout(rate=0.5)(model, training=training)
    model = tf.keras.layers.Bidirectional(tf.keras.layers.LSTM(200, return_sequences=True))(model)
    model = tf.keras.layers.Dropout(rate=0.5)(model, training=training)
    model = tf.keras.layers.Flatten()(model)
    model = tf.keras.layers.Dense(ph, activation=None)(model)

    x = tf.keras.Model(inputs=inp, outputs=model)

    x.compile(optimizer='adam', loss='mean_squared_error', metrics=[tf.keras.metrics.RootMeanSquaredError(), loss_metric1, loss_metric2, loss_metric3, loss_metric4, loss_metric5, loss_metric6])
    
    return x 


# # Load MPC results

# ## Train loss


t = np.arange(1,100)

lstm_val_loss_10 = json.load(open('../saved/history/mpc_guided_lstm_history'))['loss_metric1'][1:]
lstm_val_loss_20 = json.load(open('../saved/history/mpc_guided_lstm_history'))['loss_metric2'][1:]
lstm_val_loss_30 = json.load(open('../saved/history/mpc_guided_lstm_history'))['loss_metric3'][1:]
lstm_val_loss_40 = json.load(open('../saved/history/mpc_guided_lstm_history'))['loss_metric4'][1:]
lstm_val_loss_50 = json.load(open('../saved/history/mpc_guided_lstm_history'))['loss_metric5'][1:]
lstm_val_loss_60 = json.load(open('../saved/history/mpc_guided_lstm_history'))['loss_metric6'][1:]

crnn_val_loss_10 = json.load(open('../saved/history/mpc_guided_crnn_history'))['loss_metric1'][1:]
crnn_val_loss_20 = json.load(open('../saved/history/mpc_guided_crnn_history'))['loss_metric2'][1:]
crnn_val_loss_30 = json.load(open('../saved/history/mpc_guided_crnn_history'))['loss_metric3'][1:]
crnn_val_loss_40 = json.load(open('../saved/history/mpc_guided_crnn_history'))['loss_metric4'][1:]
crnn_val_loss_50 = json.load(open('../saved/history/mpc_guided_crnn_history'))['loss_metric5'][1:]
crnn_val_loss_60 = json.load(open('../saved/history/mpc_guided_crnn_history'))['loss_metric6'][1:]

bilstm_val_loss_10 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['loss_metric1'][1:]
bilstm_val_loss_20 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['loss_metric2'][1:]
bilstm_val_loss_30 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['loss_metric3'][1:]
bilstm_val_loss_40 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['loss_metric4'][1:]
bilstm_val_loss_50 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['loss_metric5'][1:]
bilstm_val_loss_60 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['loss_metric6'][1:]

fig, axes = plt.subplots(2,3)

axes[0,0].plot(t, np.sqrt(lstm_val_loss_10), label='LSTM')
axes[0,1].plot(t, np.sqrt(lstm_val_loss_20), label='LSTM')
axes[0,2].plot(t, np.sqrt(lstm_val_loss_30), label='LSTM')
axes[1,0].plot(t, np.sqrt(lstm_val_loss_40), label='LSTM')
axes[1,1].plot(t, np.sqrt(lstm_val_loss_50), label='LSTM')
axes[1,2].plot(t, np.sqrt(lstm_val_loss_60), label='LSTM')

axes[0,0].plot(t, np.sqrt(crnn_val_loss_10), label='CRNN')
axes[0,1].plot(t, np.sqrt(crnn_val_loss_20), label='CRNN')
axes[0,2].plot(t, np.sqrt(crnn_val_loss_30), label='CRNN')
axes[1,0].plot(t, np.sqrt(crnn_val_loss_40), label='CRNN')
axes[1,1].plot(t, np.sqrt(crnn_val_loss_50), label='CRNN')
axes[1,2].plot(t, np.sqrt(crnn_val_loss_60), label='CRNN')

axes[0,0].plot(t, np.sqrt(bilstm_val_loss_10), label='Bidirectional LSTM')
axes[0,1].plot(t, np.sqrt(bilstm_val_loss_20), label='Bidirectional LSTM')
axes[0,2].plot(t, np.sqrt(bilstm_val_loss_30), label='Bidirectional LSTM')
axes[1,0].plot(t, np.sqrt(bilstm_val_loss_40), label='Bidirectional LSTM')
axes[1,1].plot(t, np.sqrt(bilstm_val_loss_50), label='Bidirectional LSTM')
axes[1,2].plot(t, np.sqrt(bilstm_val_loss_60), label='Bidirectional LSTM')

axes[0,0].title.set_text('10 minute prediction train loss')
axes[0,1].title.set_text('20 minute prediction train loss')
axes[0,2].title.set_text('30 minute prediction train loss')
axes[1,0].title.set_text('40 minute prediction train loss')
axes[1,1].title.set_text('50 minute prediction train loss')
axes[1,2].title.set_text('60 minute prediction train loss')

axes[0,0].set_ylabel('RMSE (mmol/L)')
axes[1,0].set_ylabel('RMSE (mmol/L)')
axes[1,0].set_xlabel('Epochs')
axes[1,1].set_xlabel('Epochs')
axes[1,2].set_xlabel('Epochs')

axes[0,0].legend()
axes[0,1].legend()
axes[0,2].legend()
axes[1,0].legend()
axes[1,1].legend()
axes[1,2].legend()

plt.rcParams["figure.figsize"] = (20,10)
custom_ylim = (0,0.8)
plt.setp(axes, ylim=custom_ylim)

plt.show()



# ## Validation loss


t = np.arange(1,100)

lstm_val_loss_10 = json.load(open('../saved/history/mpc_guided_lstm_history'))['val_loss_metric1'][1:]
lstm_val_loss_20 = json.load(open('../saved/history/mpc_guided_lstm_history'))['val_loss_metric2'][1:]
lstm_val_loss_30 = json.load(open('../saved/history/mpc_guided_lstm_history'))['val_loss_metric3'][1:]
lstm_val_loss_40 = json.load(open('../saved/history/mpc_guided_lstm_history'))['val_loss_metric4'][1:]
lstm_val_loss_50 = json.load(open('../saved/history/mpc_guided_lstm_history'))['val_loss_metric5'][1:]
lstm_val_loss_60 = json.load(open('../saved/history/mpc_guided_lstm_history'))['val_loss_metric6'][1:]

crnn_val_loss_10 = json.load(open('../saved/history/mpc_guided_crnn_history'))['val_loss_metric1'][1:]
crnn_val_loss_20 = json.load(open('../saved/history/mpc_guided_crnn_history'))['val_loss_metric2'][1:]
crnn_val_loss_30 = json.load(open('../saved/history/mpc_guided_crnn_history'))['val_loss_metric3'][1:]
crnn_val_loss_40 = json.load(open('../saved/history/mpc_guided_crnn_history'))['val_loss_metric4'][1:]
crnn_val_loss_50 = json.load(open('../saved/history/mpc_guided_crnn_history'))['val_loss_metric5'][1:]
crnn_val_loss_60 = json.load(open('../saved/history/mpc_guided_crnn_history'))['val_loss_metric6'][1:]

bilstm_val_loss_10 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['val_loss_metric1'][1:]
bilstm_val_loss_20 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['val_loss_metric2'][1:]
bilstm_val_loss_30 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['val_loss_metric3'][1:]
bilstm_val_loss_40 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['val_loss_metric4'][1:]
bilstm_val_loss_50 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['val_loss_metric5'][1:]
bilstm_val_loss_60 = json.load(open('../saved/history/mpc_guided_bilstm_history'))['val_loss_metric6'][1:]

plt.rcParams["figure.figsize"] = (20,10)
fig, axes = plt.subplots(2,3)

axes[0,0].plot(t, np.sqrt(lstm_val_loss_10), label='LSTM')
axes[0,1].plot(t, np.sqrt(lstm_val_loss_20), label='LSTM')
axes[0,2].plot(t, np.sqrt(lstm_val_loss_30), label='LSTM')
axes[1,0].plot(t, np.sqrt(lstm_val_loss_40), label='LSTM')
axes[1,1].plot(t, np.sqrt(lstm_val_loss_50), label='LSTM')
axes[1,2].plot(t, np.sqrt(lstm_val_loss_60), label='LSTM')

axes[0,0].plot(t, np.sqrt(crnn_val_loss_10), label='CRNN')
axes[0,1].plot(t, np.sqrt(crnn_val_loss_20), label='CRNN')
axes[0,2].plot(t, np.sqrt(crnn_val_loss_30), label='CRNN')
axes[1,0].plot(t, np.sqrt(crnn_val_loss_40), label='CRNN')
axes[1,1].plot(t, np.sqrt(crnn_val_loss_50), label='CRNN')
axes[1,2].plot(t, np.sqrt(crnn_val_loss_60), label='CRNN')

axes[0,0].plot(t, np.sqrt(bilstm_val_loss_10), label='Bidirectional LSTM')
axes[0,1].plot(t, np.sqrt(bilstm_val_loss_20), label='Bidirectional LSTM')
axes[0,2].plot(t, np.sqrt(bilstm_val_loss_30), label='Bidirectional LSTM')
axes[1,0].plot(t, np.sqrt(bilstm_val_loss_40), label='Bidirectional LSTM')
axes[1,1].plot(t, np.sqrt(bilstm_val_loss_50), label='Bidirectional LSTM')
axes[1,2].plot(t, np.sqrt(bilstm_val_loss_60), label='Bidirectional LSTM')

axes[0,0].title.set_text('10 minute prediction validation loss')
axes[0,1].title.set_text('20 minute prediction validation loss')
axes[0,2].title.set_text('30 minute prediction validation loss')
axes[1,0].title.set_text('40 minute prediction validation loss')
axes[1,1].title.set_text('50 minute prediction validation loss')
axes[1,2].title.set_text('60 minute prediction validation loss')

axes[0,0].set_ylabel('RMSE (mmol/L)')
axes[1,0].set_ylabel('RMSE (mmol/L)')
axes[1,0].set_xlabel('Epochs')
axes[1,1].set_xlabel('Epochs')
axes[1,2].set_xlabel('Epochs')

axes[0,0].legend()
axes[0,1].legend()
axes[0,2].legend()
axes[1,0].legend()
axes[1,1].legend()
axes[1,2].legend()

custom_ylim = (0,0.8)
plt.setp(axes, ylim=custom_ylim)


plt.show()


# # Load UVA results

# ## Train loss

t = np.arange(1,100)

lstm_val_loss_10 = json.load(open('../saved/history/uva_padova_lstm_history'))['loss_metric1'][1:]
lstm_val_loss_20 = json.load(open('../saved/history/uva_padova_lstm_history'))['loss_metric2'][1:]
lstm_val_loss_30 = json.load(open('../saved/history/uva_padova_lstm_history'))['loss_metric3'][1:]
lstm_val_loss_40 = json.load(open('../saved/history/uva_padova_lstm_history'))['loss_metric4'][1:]
lstm_val_loss_50 = json.load(open('../saved/history/uva_padova_lstm_history'))['loss_metric5'][1:]
lstm_val_loss_60 = json.load(open('../saved/history/uva_padova_lstm_history'))['loss_metric6'][1:]

crnn_val_loss_10 = json.load(open('../saved/history/uva_padova_crnn_history'))['loss_metric1'][1:]
crnn_val_loss_20 = json.load(open('../saved/history/uva_padova_crnn_history'))['loss_metric2'][1:]
crnn_val_loss_30 = json.load(open('../saved/history/uva_padova_crnn_history'))['loss_metric3'][1:]
crnn_val_loss_40 = json.load(open('../saved/history/uva_padova_crnn_history'))['loss_metric4'][1:]
crnn_val_loss_50 = json.load(open('../saved/history/uva_padova_crnn_history'))['loss_metric5'][1:]
crnn_val_loss_60 = json.load(open('../saved/history/uva_padova_crnn_history'))['loss_metric6'][1:]

bilstm_val_loss_10 = json.load(open('../saved/history/uva_padova_bilstm_history'))['loss_metric1'][1:]
bilstm_val_loss_20 = json.load(open('../saved/history/uva_padova_bilstm_history'))['loss_metric2'][1:]
bilstm_val_loss_30 = json.load(open('../saved/history/uva_padova_bilstm_history'))['loss_metric3'][1:]
bilstm_val_loss_40 = json.load(open('../saved/history/uva_padova_bilstm_history'))['loss_metric4'][1:]
bilstm_val_loss_50 = json.load(open('../saved/history/uva_padova_bilstm_history'))['loss_metric5'][1:]
bilstm_val_loss_60 = json.load(open('../saved/history/uva_padova_bilstm_history'))['loss_metric6'][1:]

fig, axes = plt.subplots(2,3)
plt.rcParams["figure.figsize"] = (20,10)

axes[0,0].plot(t, np.sqrt(lstm_val_loss_10), label='LSTM')
axes[0,1].plot(t, np.sqrt(lstm_val_loss_20), label='LSTM')
axes[0,2].plot(t, np.sqrt(lstm_val_loss_30), label='LSTM')
axes[1,0].plot(t, np.sqrt(lstm_val_loss_40), label='LSTM')
axes[1,1].plot(t, np.sqrt(lstm_val_loss_50), label='LSTM')
axes[1,2].plot(t, np.sqrt(lstm_val_loss_60), label='LSTM')

axes[0,0].plot(t, np.sqrt(crnn_val_loss_10), label='CRNN')
axes[0,1].plot(t, np.sqrt(crnn_val_loss_20), label='CRNN')
axes[0,2].plot(t, np.sqrt(crnn_val_loss_30), label='CRNN')
axes[1,0].plot(t, np.sqrt(crnn_val_loss_40), label='CRNN')
axes[1,1].plot(t, np.sqrt(crnn_val_loss_50), label='CRNN')
axes[1,2].plot(t, np.sqrt(crnn_val_loss_60), label='CRNN')

axes[0,0].plot(t, np.sqrt(bilstm_val_loss_10), label='Bidirectional LSTM')
axes[0,1].plot(t, np.sqrt(bilstm_val_loss_20), label='Bidirectional LSTM')
axes[0,2].plot(t, np.sqrt(bilstm_val_loss_30), label='Bidirectional LSTM')
axes[1,0].plot(t, np.sqrt(bilstm_val_loss_40), label='Bidirectional LSTM')
axes[1,1].plot(t, np.sqrt(bilstm_val_loss_50), label='Bidirectional LSTM')
axes[1,2].plot(t, np.sqrt(bilstm_val_loss_60), label='Bidirectional LSTM')

axes[0,0].title.set_text('10 minute prediction train loss')
axes[0,1].title.set_text('20 minute prediction train loss')
axes[0,2].title.set_text('30 minute prediction train loss')
axes[1,0].title.set_text('40 minute prediction train loss')
axes[1,1].title.set_text('50 minute prediction train loss')
axes[1,2].title.set_text('60 minute prediction train loss')

axes[0,0].set_ylabel('RMSE (mmol/L)')
axes[1,0].set_ylabel('RMSE (mmol/L)')
axes[1,0].set_xlabel('Epochs')
axes[1,1].set_xlabel('Epochs')
axes[1,2].set_xlabel('Epochs')

axes[0,0].legend()
axes[0,1].legend()
axes[0,2].legend()
axes[1,0].legend()
axes[1,1].legend()
axes[1,2].legend()

custom_ylim = (0,1.2)
plt.setp(axes, ylim=custom_ylim)


plt.show()


# ## Validation loss


t = np.arange(1,100)

lstm_val_loss_10 = json.load(open('../saved/history/uva_padova_lstm_history'))['val_loss_metric1'][1:]
lstm_val_loss_20 = json.load(open('../saved/history/uva_padova_lstm_history'))['val_loss_metric2'][1:]
lstm_val_loss_30 = json.load(open('../saved/history/uva_padova_lstm_history'))['val_loss_metric3'][1:]
lstm_val_loss_40 = json.load(open('../saved/history/uva_padova_lstm_history'))['val_loss_metric4'][1:]
lstm_val_loss_50 = json.load(open('../saved/history/uva_padova_lstm_history'))['val_loss_metric5'][1:]
lstm_val_loss_60 = json.load(open('../saved/history/uva_padova_lstm_history'))['val_loss_metric6'][1:]

crnn_val_loss_10 = json.load(open('../saved/history/uva_padova_crnn_history'))['val_loss_metric1'][1:]
crnn_val_loss_20 = json.load(open('../saved/history/uva_padova_crnn_history'))['val_loss_metric2'][1:]
crnn_val_loss_30 = json.load(open('../saved/history/uva_padova_crnn_history'))['val_loss_metric3'][1:]
crnn_val_loss_40 = json.load(open('../saved/history/uva_padova_crnn_history'))['val_loss_metric4'][1:]
crnn_val_loss_50 = json.load(open('../saved/history/uva_padova_crnn_history'))['val_loss_metric5'][1:]
crnn_val_loss_60 = json.load(open('../saved/history/uva_padova_crnn_history'))['val_loss_metric6'][1:]

bilstm_val_loss_10 = json.load(open('../saved/history/uva_padova_bilstm_history'))['val_loss_metric1'][1:]
bilstm_val_loss_20 = json.load(open('../saved/history/uva_padova_bilstm_history'))['val_loss_metric2'][1:]
bilstm_val_loss_30 = json.load(open('../saved/history/uva_padova_bilstm_history'))['val_loss_metric3'][1:]
bilstm_val_loss_40 = json.load(open('../saved/history/uva_padova_bilstm_history'))['val_loss_metric4'][1:]
bilstm_val_loss_50 = json.load(open('../saved/history/uva_padova_bilstm_history'))['val_loss_metric5'][1:]
bilstm_val_loss_60 = json.load(open('../saved/history/uva_padova_bilstm_history'))['val_loss_metric6'][1:]

fig, axes = plt.subplots(2,3)
plt.rcParams["figure.figsize"] = (20,10)

axes[0,0].plot(t, np.sqrt(lstm_val_loss_10), label='LSTM')
axes[0,1].plot(t, np.sqrt(lstm_val_loss_20), label='LSTM')
axes[0,2].plot(t, np.sqrt(lstm_val_loss_30), label='LSTM')
axes[1,0].plot(t, np.sqrt(lstm_val_loss_40), label='LSTM')
axes[1,1].plot(t, np.sqrt(lstm_val_loss_50), label='LSTM')
axes[1,2].plot(t, np.sqrt(lstm_val_loss_60), label='LSTM')

axes[0,0].plot(t, np.sqrt(crnn_val_loss_10), label='CRNN')
axes[0,1].plot(t, np.sqrt(crnn_val_loss_20), label='CRNN')
axes[0,2].plot(t, np.sqrt(crnn_val_loss_30), label='CRNN')
axes[1,0].plot(t, np.sqrt(crnn_val_loss_40), label='CRNN')
axes[1,1].plot(t, np.sqrt(crnn_val_loss_50), label='CRNN')
axes[1,2].plot(t, np.sqrt(crnn_val_loss_60), label='CRNN')

axes[0,0].plot(t, np.sqrt(bilstm_val_loss_10), label='Bidirectional LSTM')
axes[0,1].plot(t, np.sqrt(bilstm_val_loss_20), label='Bidirectional LSTM')
axes[0,2].plot(t, np.sqrt(bilstm_val_loss_30), label='Bidirectional LSTM')
axes[1,0].plot(t, np.sqrt(bilstm_val_loss_40), label='Bidirectional LSTM')
axes[1,1].plot(t, np.sqrt(bilstm_val_loss_50), label='Bidirectional LSTM')
axes[1,2].plot(t, np.sqrt(bilstm_val_loss_60), label='Bidirectional LSTM')

axes[0,0].title.set_text('10 minute prediction validation loss')
axes[0,1].title.set_text('20 minute prediction validation loss')
axes[0,2].title.set_text('30 minute prediction validation loss')
axes[1,0].title.set_text('40 minute prediction validation loss')
axes[1,1].title.set_text('50 minute prediction validation loss')
axes[1,2].title.set_text('60 minute prediction validation loss')

axes[0,0].set_ylabel('RMSE (mmol/L)')
axes[1,0].set_ylabel('RMSE (mmol/L)')
axes[1,0].set_xlabel('Epochs')
axes[1,1].set_xlabel('Epochs')
axes[1,2].set_xlabel('Epochs')

axes[0,0].legend()
axes[0,1].legend()
axes[0,2].legend()
axes[1,0].legend()
axes[1,1].legend()
axes[1,2].legend()

custom_ylim = (0,1.2)
plt.setp(axes, ylim=custom_ylim)

plt.show()


# # Total insulin

print('Loading data....')


uva_train, _ = load_uva(12,6,10,False)
mpc_train, _ = load_mpc(12,6,10,False)

plt.plot(np.arange(144)*10, uva_train[0,2,:])
plt.xlabel('Minutes')
plt.ylabel('Units')
plt.show()

plt.plot(np.arange(144)*10, mpc_train[0,2,:])
plt.xlabel('Minutes')
plt.ylabel('Units')
plt.show()

