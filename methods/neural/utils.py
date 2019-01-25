import tensorflow as tf
import numpy as np
import operator

from nltk import tokenize as nltk_token

def splitY(model, y_data, feed_dict):
    for i in range(len(model.target_cols)):
        feed_dict[model.task_outputs[model.target_cols[i]]] = y_data[:, i]
    return feed_dict

def build_embedding(pretrain, train_embedding, embedding_size, vocab_size):
    if pretrain:
        # TODO: Added a 1 into shape
        embeddings_variable = tf.Variable(tf.constant(0.0, shape=[vocab_size, embedding_size, 1]),
                                 trainable=train_embedding, name="W")
    else:
        embeddings_variable = tf.get_variable("embedding",
                                                initializer=tf.random_uniform(
                                                    [vocab_size, embedding_size], -1, 1),
                                                dtype=tf.float32)
    return embeddings_variable

def weight_placeholder(target_cols):
    weights = dict()
    for target in target_cols:
        weights[target] = tf.placeholder(tf.float64, [None], name=target + "_w")
    return weights

def multi_GRU(cell, hidden_size, keep_ratio, num_layers):
    if cell == "LSTM":
        cell = tf.contrib.rnn.BasicLSTMCell(num_units=hidden_size, reuse=tf.AUTO_REUSE)
    elif cell == "GRU":
        cell = tf.contrib.rnn.GRUCell(num_units=hidden_size)
    cell_drop = tf.contrib.rnn.DropoutWrapper(cell, input_keep_prob=keep_ratio)
    network = tf.contrib.rnn.MultiRNNCell([cell_drop] * num_layers)
    return network

def dynamic_rnn(model, network, embed, sequence_length):
    if model == "LSTM" or model == "RCNN":
        rnn_outputs, state = tf.nn.dynamic_rnn(network, embed,
                                               dtype=tf.float32, sequence_length=sequence_length)
    else:#elif model == "BiLSTM":
        bi_outputs, bi_states = tf.nn.bidirectional_dynamic_rnn(network, network, embed,
                                                                dtype=tf.float32,
                                                                sequence_length=sequence_length)
        fw_outputs, bw_outputs = bi_outputs
        fw_states, bw_states = bi_states
        rnn_outputs = tf.concat([fw_outputs, bw_outputs], 2)
        state = tf.concat([fw_states, bw_states], 2)

    return rnn_outputs, state

def multi_outputs(target_cols):
    outputs = dict()
    for target in target_cols:
        y = tf.placeholder(tf.int64, [None], name=target)
        outputs[target] = y
    return outputs


def pred(hidden, n_outputs, weights, task_outputs):
    logits = tf.layers.dense(inputs=hidden, units=n_outputs)

    weight = tf.gather(weights, task_outputs)
    xentropy = tf.losses.sparse_softmax_cross_entropy(labels=task_outputs,
                                                      logits=logits,
                                                      weights=weight)
    loss = tf.reduce_mean(xentropy)
    predicted_label = tf.argmax(logits, 1)
    accuracy = tf.reduce_mean(
        tf.cast(tf.equal(predicted_label, task_outputs), tf.float32))

    return loss, predicted_label, accuracy


def drop_padding(self, output, length):
    relevant = tf.gather(output, length, axis = 1)
    return relevant

def run(model, batches, test_batches, weights):
    init = tf.global_variables_initializer()
    with tf.Session() as model.sess:
        done = False
        init.run()
        print("Learning vocabulary of size %d" % (vocab_size))
        epoch = 1
        test_predictions = {target: np.array([]) for target in model.target_cols}
        hate_pred = list()
        while True:
            ## Train
            epoch_loss = float(0)
            acc_train = 0
            epoch += 1
            for batch in batches:
                feed_dict = feed_dictionary(model, batch, weights)
                _, loss_val = model.sess.run([model.training_op, model.joint_loss], feed_dict= feed_dict)
                acc_train += model.joint_accuracy.eval(feed_dict=feed_dict)
                epoch_loss += loss_val
            if epoch >= model.epochs and acc_train / float(len(batches)) > 0.8:
                #print(1)
                done = True
            if epoch == 200:
                #print(3)
                done = True
            ## Test
            acc_test = 0
            for batch in test_batches:
                feed_dict = feed_dictionary(model, batch, weights)
                acc_test += model.joint_accuracy.eval(feed_dict=feed_dict)
                if done:
                    for target in model.target_cols:
                        test_predictions[target] = np.append(test_predictions[target],
                                                             model.predict[target].eval(feed_dict=feed_dict))
                    hate_pred.extend(list(model.predict["hate"].eval(feed_dict=feed_dict)))

            print(epoch, "Train accuracy:", acc_train / float(len(batches)),
                  "Loss: ", epoch_loss / float(len(batches)),
                  "Test accuracy: ", acc_test / float(len(test_batches)))

            if done:
                test_predictions = np.transpose(np.array([test_predictions[target] for target in model.target_cols]))
                break
        #save_path = saver.save(model.sess, "/tmp/model.ckpt")
    return hate_pred, acc_test / float(len(test_batches))

def feed_dictionary(model, batch, weights):
    X_batch, X_len, y_batch = batch
    feed_dict = splitY(model, y_batch, {model.train_inputs: X_batch,
                                        model.sequence_length: X_len,
                                        model.keep_prob: model.keep_ratio})
                                        # model.max_length: max(X_len)
    for t in model.target_cols:
        feed_dict[model.weights[t]] = weights[t]
    if model.pretrain:
        feed_dict[model.embedding_placeholder] = model.my_embeddings
    return feed_dict

def cnn(input, filter_sizes, num_filters, keep_ratio):
    pooled_outputs = list()
    for i, filter_size in enumerate(filter_sizes):
        filter_shape = [filter_size, int(input.get_shape()[2]), 1, num_filters]
        b = tf.Variable(tf.constant(0.1, shape=[num_filters]))
        W = tf.Variable(tf.truncated_normal(filter_shape, stddev=0.1), name="W")

        conv = tf.nn.conv2d(input, W, strides=[1, 1, 1, 1], padding="VALID")
        relu = tf.nn.relu(tf.nn.bias_add(conv, b))

        pooled = tf.reduce_max(relu, axis=1, keep_dims=True)
        pooled_outputs.append(pooled)

    num_filters_total = num_filters * len(filter_sizes)
    h_pool = tf.concat(values=pooled_outputs, axis=3)
    h_pool_flat = tf.reshape(h_pool, [-1, num_filters_total])

    output = tf.nn.dropout(h_pool_flat, keep_ratio)
    return output

def tokenize_data(corpus):
    #sent_tokenizer = toks[self.params["tokenize"]]
    tokenized_corpus = [nltk_token.WordPunctTokenizer().tokenize(sent.lower()) for sent in corpus]
    return tokenized_corpus

def learn_vocab(corpus, vocab_size):
    print("Learning vocabulary of size %d" % (vocab_size))
    tokens = dict()
    for sent in corpus:
        for token in sent:
            if token in tokens:
                tokens[token] += 1
            else:
                tokens[token] = 1
    words, counts = zip(*sorted(tokens.items(), key=operator.itemgetter(1), reverse=True))
    vocab = list(words[:vocab_size]) + ["<unk>", "<pad>"]
    return vocab
