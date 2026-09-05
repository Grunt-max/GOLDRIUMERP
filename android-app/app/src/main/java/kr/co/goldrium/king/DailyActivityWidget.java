package kr.co.goldrium.king;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;

public class DailyActivityWidget extends AppWidgetProvider {
    @Override public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) {
            RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.daily_activity_widget);
            bind(context, views, R.id.activity_add, "entry", 1);
            bind(context, views, R.id.activity_list, "list", 2);
            manager.updateAppWidget(id, views);
        }
    }

    private void bind(Context context, RemoteViews views, int viewId, String destination, int requestCode) {
        Intent intent = new Intent(context, MainActivity.class)
            .putExtra("activity_destination", destination)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        views.setOnClickPendingIntent(viewId, PendingIntent.getActivity(context, requestCode, intent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
    }
}
