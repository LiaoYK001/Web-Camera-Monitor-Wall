import QtQuick
import QtQuick.Controls
import org.freedesktop.gstreamer.Qt6GLVideoItem 1.0

Item {
    id: root
    property string title: "Camera"
    property alias videoItem: video

    Rectangle {
        anchors.fill: parent
        color: "#05070a"
        border.color: "#273244"
        border.width: 1
        GstGLVideoItem {
            id: video
            anchors.fill: parent
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 34
            color: "#b010141c"
            Text {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.leftMargin: 10
                color: "white"
                text: root.title
                elide: Text.ElideRight
            }
        }
    }
}
